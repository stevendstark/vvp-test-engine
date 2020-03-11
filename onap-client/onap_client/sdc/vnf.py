# -*- coding: utf8 -*-
# ============LICENSE_START=======================================================
# org.onap.vvp/validation-scripts
# ===================================================================
# Copyright © 2020 AT&T Intellectual Property. All rights reserved.
# ===================================================================
#
# Unless otherwise specified, all software contained herein is licensed
# under the Apache License, Version 2.0 (the "License");
# you may not use this software except in compliance with the License.
# You may obtain a copy of the License at
#
#             http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
#
# Unless otherwise specified, all documentation contained herein is licensed
# under the Creative Commons License, Attribution 4.0 Intl. (the "License");
# you may not use this documentation except in compliance with the License.
# You may obtain a copy of the License at
#
#             https://creativecommons.org/licenses/by/4.0/
#
# Unless required by applicable law or agreed to in writing, documentation
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# ============LICENSE_END============================================

from onap_client.lib import generate_dummy_string
from onap_client.resource import Resource
from onap_client import exceptions, sdc
from onap_client.client.clients import Client as SDCClient
from onap_client.sdc import vsp
from onap_client.util import utility

import time

vnf_client = SDCClient().sdc.vnf


class VNF(Resource):
    resource_name = "VNF"
    spec = {
        "software_product_name": {"type": str, "required": True},
        "vnf_name": {
            "type": str,
            "required": False,
            "default": generate_dummy_string("test_vnf_"),
        },
        "resource_type": {"type": str, "required": False, "default": "VF"},
        "inputs": {"type": dict, "required": False, "default": {}},
        "vm_types": {
            "type": list,
            "list_item": dict,
            "required": False,
            "default": [],
            "nested": {
                "vm_type": {"type": str, "required": True},
                "properties": {"type": dict, "required": True, "default": {}},
            },
        },
        "network_roles": {
            "type": list,
            "list_item": dict,
            "required": False,
            "default": [],
            "nested": {
                "network_role_tag": {"type": str, "required": True},
                "network_role": {"type": str, "required": True},
                "related_networks": {
                    "type": list,
                    "list_item": str,
                    "required": False,
                    "default": [],
                },
            },
        },
        "policies": {
            "type": list,
            "list_item": dict,
            "required": False,
            "default": [],
            "nested": {
                "policy_name": {"type": str, "required": True},
                "properties": {"type": dict, "required": False, "default": {}},
            },
        },
    }

    def __init__(
        self,
        software_product_name,
        vnf_name,
        resource_type,
        inputs={},
        vm_types=[],
        network_roles=[],
        policies=[],
    ):

        vnf_input = {}

        software_product_id = vsp.get_vsp_id(software_product_name)
        software_product_version_id = vsp.get_vsp_version_id(software_product_id)
        vsp_model = vsp.get_vsp_model(software_product_id, software_product_version_id)
        vsp_vendor = vsp_model.get("vendorName")

        vnf_input["software_product_id"] = software_product_id
        vnf_input["vendor_name"] = vsp_vendor
        vnf_input["vnf_name"] = vnf_name
        vnf_input["resource_type"] = resource_type
        vnf_input["inputs"] = inputs
        vnf_input["vm_types"] = vm_types
        vnf_input["network_roles"] = network_roles
        vnf_input["policies"] = policies

        super().__init__(vnf_input)

    def _create(self, vnf_input):
        """Creates a vnf object in SDC"""
        vnf = None

        if get_vnf_id(vnf_input.get("vnf_name")) is None:
            vnf = create_vnf(vnf_input)
        else:
            raise exceptions.ResourceAlreadyExistsException(
                "VNF resource {} already exists".format(vnf_input.get("vnf_name"))
            )

        return vnf

    def _post_create(self):
        inputs = self.inputs
        vm_types = self.vm_types
        network_roles = self.network_roles
        policies = self.policies
        model = self.tosca
        vm_type_instances = []

        for vm_type in vm_types:
            vm_type_tag = vm_type.get("vm_type")
            properties = vm_type.get("properties")
            instance_ids = instance_ids_for_property(model, "vm_type_tag", vm_type_tag)
            for instance_id in instance_ids:
                for k, v in properties.items():
                    # updating vm_type properties
                    self.add_instance_property(instance_id, k, v)
                    vm_type_instances.append(instance_id)
                for network_role in network_roles:
                    # checking if abstract node has matching network role,
                    # and updating if found
                    nrt = network_role.get("network_role_tag")
                    nr = network_role.get("network_role")
                    related_networks = network_role.get("related_networks")
                    instance_property = network_role_property_for_instance(
                        nrt, model, instance_id
                    )
                    if instance_property:
                        self.add_instance_property(instance_id, instance_property, nr)
                        if related_networks:
                            property_val = [
                                {"related_network_role": related_network_role}
                                for related_network_role in related_networks
                            ]
                            rnr_instance_property = instance_property.replace(
                                "_network_role", "_related_networks"
                            )
                            self.add_instance_property(
                                instance_id,
                                rnr_instance_property,
                                str(property_val).replace("'", '\\"'),
                            )

        for policy in policies:
            policy_name = policy.get("policy_name")
            policy_model = self.add_policy_resource(policy_name)
            self.associate_policy(policy_model.catalog_resource_id, vm_type_instances)
            for k, v in policy.get("properties", {}).items():
                self.add_policy_property(policy_model.catalog_resource_id, k, v)

        for k, v in inputs.items():
            self.add_input_value(k, v)

    def _submit(self):
        """Submits the vnf in SDC"""
        certification = vnf_client.certify_catalog_resource(
            **self.attributes, user_remarks="Ready!"
        )
        self.attributes["catalog_resource_id"] = certification.catalog_resource_id

        vnf = vnf_client.get_catalog_resource(**self.attributes)

        self.attributes["catalog_resource_name"] = vnf.catalog_resource_name
        self.attributes["tosca"] = vnf.response_data

    def add_resource(
        self, catalog_resource_id, catalog_resource_name, origin_type="VF"
    ):
        """Attaches a resource to a VNF in SDC

        :catalog_resource_id: ID of a resource in the SDC catalog
        :catalog_resource_name: name to give to the resource when attaching to vnf
        :origin_type: specifies the origin of the attached resource

        """
        milli_timestamp = int(time.time() * 1000)

        resource_instance = vnf_client.add_resource_instance(
            **self.attributes,
            posX=306,
            posY=248,
            milli_timestamp=milli_timestamp,
            new_catalog_resource_id=catalog_resource_id,
            new_catalog_resource_name=catalog_resource_name,
            originType=origin_type,
        )

        response = {
            "id": resource_instance.catalog_resource_instance_id,
            "tosca": resource_instance.response_data,
        }
        self.attributes[catalog_resource_name] = response

    def add_input_value(self, input_name, input_default_value):
        """Updates an input value on a VNF

        :input_name: input name to update
        :property_value: value to update input with

        """
        self._refresh()

        inputs = self.tosca.get("inputs", [])
        for item in inputs:
            if item["name"] == input_name:
                unique_id = item["uniqueId"]
                parent_unique_id = item["parentUniqueId"]
                owner_id = item["ownerId"]
                return vnf_client.add_catalog_resource_input(
                    **self.attributes,
                    input_default_value=input_default_value,
                    input_name=input_name,
                    input_parent_unique_id=parent_unique_id,
                    input_unique_id=unique_id,
                    input_owner_id=owner_id,
                )

        raise exceptions.InputNotFoundException(
            "Input {} was not found in VF".format(input_name)
        )

    # TODO
    # instance, policy, and group properties can probably be merged
    # rn there is a lot of dup

    def add_instance_property(self, instance_id, property_name, property_value):
        """Updates an instance property on a abstract instance attached to a VNF

        :instance_id: ID of a instance attached to a VNF
        :property_name: property name to update
        :property_value: value to update property with

        """
        self._refresh()

        instance_inputs = self.tosca.get("componentInstancesInputs", {}).get(
            instance_id, {}
        )

        for prop in instance_inputs:
            if prop.get("name") == property_name:
                unique_id = prop.get("uniqueId")
                parent_unique_id = prop.get("parentUniqueId")
                owner_id = prop.get("ownerId")
                schemaType = prop.get("schemaType", "")
                property_type = prop.get("type")
                return vnf_client.add_catalog_resource_property(
                    **self.attributes,
                    unique_id=unique_id,
                    parent_unique_id=parent_unique_id,
                    owner_id=owner_id,
                    catalog_resource_instance_id=instance_id,
                    property_name=property_name,
                    property_default_value=property_value,
                    schema_type=schemaType,
                    property_type=property_type,
                )

        raise exceptions.PropertyNotFoundException(
            "Property {} was not found in Instance {}".format(
                property_name, instance_id
            )
        )

    def add_policy_property(self, policy_id, property_name, property_value):
        """Updates a policy property on a polic attached to a VNF

        :policy_id: ID of a policy attached to a VNF
        :property_name: property name to update
        :property_value: value to update property with

        """
        self._refresh()

        policies = (
            self.tosca.get("policies", {}).get(policy_id, {}).get("properties", {})
        )

        for prop in policies:
            if prop.get("name") == property_name:
                unique_id = prop.get("uniqueId")
                property_type = prop.get("type")
                description = prop.get("description")
                return vnf_client.add_catalog_policy_property(
                    **self.attributes,
                    unique_id=unique_id,
                    catalog_policy_id=policy_id,
                    property_name=property_name,
                    property_default_value=property_value,
                    description=description,
                    property_type=property_type,
                )

        raise exceptions.PropertyNotFoundException(
            "Property {} was not found in policy {}".format(property_name, policy_id)
        )

    def add_group_property(self, group_id, property_name, property_value):
        """Updates a group property on a group attached to a VNF

        :group_id: ID of a group attached to a VNF
        :property_name: property name to update
        :property_value: value to update property with

        """
        self._refresh()

        groups = self.tosca.get("groups", [])

        for group in groups:
            if group.get("uniqueId") == group_id:
                properties = group.get("properties", [])
                for prop in properties:
                    unique_id = prop.get("uniqueId")
                    property_type = prop.get("type")
                    description = prop.get("description")
                    parent_unique_id = prop.get("parentUniqueId")
                    owner_id = prop.get("ownerId")
                    return vnf_client.add_catalog_group_property(
                        **self.attributes,
                        unique_id=unique_id,
                        catalog_group_id=group_id,
                        property_name=property_name,
                        property_default_value=property_value,
                        description=description,
                        property_type=property_type,
                        parent_unique_id=parent_unique_id,
                        owner_id=owner_id,
                    )

        raise exceptions.PropertyNotFoundException(
            "Property {} was not found in group {}".format(property_name, group_id)
        )

    def add_group_resource(self, group_name):
        """Adds an SDC group resource to a VNF

        :group_name: name of the group, matching onap-client.conf

        """
        sdc_properties = sdc.SDC_PROPERTIES
        group = sdc_properties.GROUPS.get(group_name)
        if not group:
            raise exceptions.UnknownGroupException(
                "Group {} was not found in configuration file".format(group_name)
            )

        return vnf_client.add_catalog_resource_group(
            **self.attributes, catalog_group_name=group
        )

    def add_policy_resource(self, policy_name):
        """Adds an SDC policy resource to a VNF

        :group_name: name of the policy, matching onap-client.conf

        """
        sdc_properties = sdc.SDC_PROPERTIES
        policy = sdc_properties.POLICIES.get(policy_name)
        if not policy:
            raise exceptions.UnknownPolicyException(
                "Policy {} was not found in configuration file".format(policy_name)
            )

        return vnf_client.add_catalog_resource_policy(
            **self.attributes, catalog_policy_name=policy
        )

    def associate_policy(self, policy_id, instance_ids):
        """associates an SDC policy resource to an VNF instance resource

        :policy_id: ID of policy resource from catalog
        :instance_ids: list of instance ids to associate policy with

        """

        return vnf_client.add_policy_to_instance(
            **self.attributes, catalog_policy_id=policy_id, instance_ids=instance_ids
        )

    def associate_group(self, group_id, instance_id):
        """associates an SDC group resource to an VNF instance resource"""
        return vnf_client.add_group_to_instance(
            **self.attributes, catalog_group_id=group_id, instance_id=instance_id
        )

    def _refresh(self):
        """GETs the VNF model from SDC and updates the VNF object"""
        vnf = vnf_client.get_catalog_resource(**self.attributes)
        self.attributes["tosca"] = vnf.response_data


def create_vnf(vnf_input):
    """Creates a vnf object in SDC

    :vnf_input: dictionary with values to input for vnf creation

    :return: dictionary of updated values for created vnf
    """
    kwargs = vnf_input
    vnf = vnf_client.add_catalog_resource(**kwargs)

    kwargs["catalog_resource_id"] = vnf.catalog_resource_id
    kwargs["tosca"] = vnf.response_data

    return kwargs


def instance_ids_for_property(vnf_model, property_name, property_value):
    """Parses a VNF model dictionary for a property + property value, to find the
    abstract node tosca uuid

    :vnf_model: dictionary for a VNF tosca model
    :property_name: name of a property to look for in the vnf model
    :property_value: value of a property to look for in the vnf model

    :return: matching [instance_ids] or []
    """
    instance_ids = []
    instances = vnf_model.get("componentInstancesInputs", {})
    for instance_id, properties in instances.items():
        for prop in properties:
            if (
                prop.get("name") == property_name
                and prop.get("value", "") == property_value
            ):
                instance_ids.append(instance_id)
                break

    return instance_ids


def network_role_property_for_instance(network_role_tag, vnf_model, instance_id):
    """Parses a VNF model dictionary for a network_role_tag property, to find the
    corresponding network role property

    :network_role_tag: the network role tag to search for
    :vnf_model: dictionary for a VNF tosca model
    :instance_id: unique ID for an abstract node to look for the network_tag_property

    :return: network_role property ID or None
    """
    instance_inputs = vnf_model.get("componentInstancesInputs", {}).get(instance_id, {})
    for prop in instance_inputs:
        if prop.get("name").endswith(
            "network_role_tag"
        ) and network_role_tag == prop.get("value"):
            network_role_property = prop.get("name").replace("_tag", "")
            return network_role_property

    return None


@utility
def get_vnf(vnf_name):
    """Queries SDC for the TOSCA model for a VNF"""
    return vnf_client.get_catalog_resource(
        catalog_resource_id=get_vnf_id(vnf_name)
    ).response_data


def get_vnf_id(vnf_name):
    response = vnf_client.get_resources()
    results = response.response_data.get("resources", [])
    for vnf in results:
        if vnf.get("name") == vnf_name:
            return vnf["uniqueId"]
    return None
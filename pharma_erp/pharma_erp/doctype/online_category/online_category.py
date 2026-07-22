from frappe.utils.nestedset import NestedSet


class OnlineCategory(NestedSet):
    nsm_parent_field = "parent_online_category"

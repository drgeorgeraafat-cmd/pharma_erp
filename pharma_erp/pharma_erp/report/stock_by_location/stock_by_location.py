import frappe
from frappe.utils import flt


def execute(filters=None):
    filters=frappe._dict(filters or {})
    columns=[
        {"label":"Item","fieldname":"item_code","fieldtype":"Link","options":"Item","width":130},
        {"label":"Item Name","fieldname":"item_name","fieldtype":"Data","width":180},
        {"label":"Item Group","fieldname":"item_group","fieldtype":"Link","options":"Item Group","width":140},
        {"label":"Warehouse","fieldname":"warehouse","fieldtype":"Link","options":"Warehouse","width":160},
        {"label":"Location","fieldname":"location","fieldtype":"Link","options":"Pharmacy Storage Location","width":160},
        {"label":"Location Code","fieldname":"location_code","fieldtype":"Data","width":110},
        {"label":"Purpose","fieldname":"purpose","fieldtype":"Data","width":90},
        {"label":"Batch","fieldname":"batch_no","fieldtype":"Link","options":"Batch","width":120},
        {"label":"Expiry","fieldname":"expiry_date","fieldtype":"Date","width":105},
        {"label":"Location Qty","fieldname":"location_qty","fieldtype":"Float","precision":6,"width":110},
        {"label":"Warehouse Qty","fieldname":"warehouse_qty","fieldtype":"Float","precision":6,"width":115},
        {"label":"Allocated Qty","fieldname":"allocated_qty","fieldtype":"Float","precision":6,"width":110},
        {"label":"Unallocated Qty","fieldname":"unallocated_qty","fieldtype":"Float","precision":6,"width":120},
    ]
    where=["1=1"]; params={}
    if filters.warehouse:
        where.append("b.warehouse=%(warehouse)s"); params["warehouse"]=filters.warehouse
    if filters.item_code:
        where.append("b.item_code=%(item_code)s"); params["item_code"]=filters.item_code
    if filters.item_group:
        where.append("i.item_group=%(item_group)s"); params["item_group"]=filters.item_group
    bins=frappe.db.sql(f"""
        SELECT b.item_code,i.item_name,i.item_group,b.warehouse,b.actual_qty AS warehouse_qty
        FROM `tabBin` b INNER JOIN `tabItem` i ON i.name=b.item_code
        WHERE {' AND '.join(where)} ORDER BY b.warehouse,b.item_code
    """,params,as_dict=True)
    data=[]
    for stock in bins:
        all_bal=frappe.get_all("Pharmacy Location Balance",filters={"warehouse":stock.warehouse,"item_code":stock.item_code},fields=["location","batch_no","qty"],order_by="location asc,batch_no asc")
        allocated=sum(flt(x.qty) for x in all_bal)
        unallocated=flt(stock.warehouse_qty-allocated,6)
        if filters.only_variance and abs(unallocated) < 1e-9:
            continue
        balances=all_bal
        if filters.location:
            balances=[x for x in balances if x.location == filters.location]
        if filters.batch_no:
            balances=[x for x in balances if (x.batch_no or "") == filters.batch_no]
        if balances:
            for bal in balances:
                loc=frappe.db.get_value("Pharmacy Storage Location",bal.location,["location_code","purpose"],as_dict=True) or {}
                expiry=frappe.db.get_value("Batch",bal.batch_no,"expiry_date") if bal.batch_no else None
                data.append({"item_code":stock.item_code,"item_name":stock.item_name,"item_group":stock.item_group,"warehouse":stock.warehouse,"location":bal.location,"location_code":loc.get("location_code"),"purpose":loc.get("purpose"),"batch_no":bal.batch_no,"expiry_date":expiry,"location_qty":flt(bal.qty,6),"warehouse_qty":flt(stock.warehouse_qty,6),"allocated_qty":flt(allocated,6),"unallocated_qty":unallocated})
        elif not filters.location and not filters.batch_no:
            data.append({"item_code":stock.item_code,"item_name":stock.item_name,"item_group":stock.item_group,"warehouse":stock.warehouse,"location":None,"location_code":None,"purpose":"Unallocated","batch_no":None,"expiry_date":None,"location_qty":0,"warehouse_qty":flt(stock.warehouse_qty,6),"allocated_qty":flt(allocated,6),"unallocated_qty":unallocated})
    return columns,data

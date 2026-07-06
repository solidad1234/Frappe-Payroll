import frappe

def main():
    # 1. Transfer Employee Penalty
    if frappe.db.exists("DocType", "Employee Penalty"):
        frappe.db.set_value("DocType", "Employee Penalty", "module", "Custom Payroll")
        print("Employee Penalty module set to Custom Payroll")

    # 2. Transfer Custom Fields
    fields_to_transfer = [
        "custom_meal_allowance",
        "custom_house_allowance",
        "custom_sacco_saving",
        "custom_adjustments",
        "custom_sacco_add_ons"
    ]
    
    for fieldname in fields_to_transfer:
        custom_field = frappe.db.get_value("Custom Field", {"dt": "Employee", "fieldname": fieldname}, "name")
        if custom_field:
            frappe.db.set_value("Custom Field", custom_field, "module", "Custom Payroll")
            print(f"Custom Field {fieldname} module set to Custom Payroll")

    frappe.db.commit()
    print("Transfer complete.")

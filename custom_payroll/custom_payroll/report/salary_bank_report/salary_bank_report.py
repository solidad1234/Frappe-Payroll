# Copyright (c) 2026, Solidad Kimeu and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data

def get_columns():
	return [
		{"fieldname": "employee_name", "label": _("Name"), "fieldtype": "Data", "width": 200},
		{"fieldname": "id_number", "label": _("ID Number"), "fieldtype": "Data", "width": 120},
		{"fieldname": "bank", "label": _("Bank"), "fieldtype": "Data", "width": 150},
		{"fieldname": "branch", "label": _("Branch"), "fieldtype": "Data", "width": 200},
		{"fieldname": "sort_code", "label": _("Sort Code"), "fieldtype": "Data", "width": 100},
		{"fieldname": "account_number", "label": _("Account Number"), "fieldtype": "Data", "width": 200},
		{"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "currency", "label": _("Currency"), "fieldtype": "Data", "hidden": 1}
	]

def get_data(filters):
	conditions = get_conditions(filters)
	
	data = frappe.db.sql(f"""
		SELECT 
			s.employee_name,
			e.custom_id as id_number,
			e.bank_name as bank,
			e.custom_bank_branch as branch,
			e.custom_sort_code as sort_code,
			e.bank_ac_no as account_number,
			s.net_pay as amount,
			s.currency
		FROM `tabSalary Slip` s
		LEFT JOIN `tabEmployee` e ON s.employee = e.name
		WHERE s.docstatus = 1 {conditions}
	""", filters, as_dict=1)

	return data

def get_conditions(filters):
	conditions = ""
	if filters.get("employee"):
		conditions += " AND s.employee = %(employee)s"
	if filters.get("from_date"):
		conditions += " AND s.start_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " AND s.end_date <= %(to_date)s"
	return conditions

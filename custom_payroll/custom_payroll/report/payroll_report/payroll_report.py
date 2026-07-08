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
		{
			"fieldname": "payroll_id",
			"label": _("Payroll ID"),
			"fieldtype": "Link",
			"options": "Employee",
			"width": 150
		},
		{
			"fieldname": "employee_name",
			"label": _("Employee Name"),
			"fieldtype": "Data",
			"width": 150
		},
		{
			"fieldname": "gross_pay",
			"label": _("Gross Pay"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
		{
			"fieldname": "paye",
			"label": _("PAYE"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
		{
			"fieldname": "nssf",
			"label": _("NSSF"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
		{
			"fieldname": "shif",
			"label": _("SHIF"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
		{
			"fieldname": "housing_levy",
			"label": _("Housing Levy"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
		{
			"fieldname": "net_pay",
			"label": _("Net Pay"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120
		},
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Data",
			"hidden": 1
		}
	]

def get_data(filters):
	conditions = get_conditions(filters)
	
	salary_slips = frappe.db.sql(f"""
		SELECT 
			name as slip_id,
			employee as payroll_id, 
			employee_name, 
			gross_pay, 
			net_pay,
			currency
		FROM `tabSalary Slip`
		WHERE docstatus = 1 {conditions}
	""", filters, as_dict=1)

	if not salary_slips:
		return []

	slip_names = [d.slip_id for d in salary_slips]
	
	deductions = frappe.db.sql("""
		SELECT 
			parent as slip_id, 
			salary_component, 
			amount 
		FROM `tabSalary Detail` 
		WHERE parentfield='deductions' 
			AND parenttype='Salary Slip'
			AND parent IN %s
	""", (tuple(slip_names),), as_dict=1)

	slip_deductions = {}
	for d in deductions:
		slip_deductions.setdefault(d.slip_id, []).append(d)

	employee_data = {}
	for slip in salary_slips:
		emp = slip.payroll_id
		if emp not in employee_data:
			employee_data[emp] = {
				"payroll_id": emp,
				"employee_name": slip.employee_name,
				"gross_pay": 0.0,
				"net_pay": 0.0,
				"paye": 0.0,
				"nssf": 0.0,
				"shif": 0.0,
				"housing_levy": 0.0,
				"currency": slip.currency
			}
		
		employee_data[emp]["gross_pay"] += (slip.gross_pay or 0.0)
		employee_data[emp]["net_pay"] += (slip.net_pay or 0.0)

		for d in slip_deductions.get(slip.slip_id, []):
			comp = (d.salary_component or "").upper()
			if "PAYE" in comp:
				employee_data[emp]["paye"] += d.amount
			elif "NSSF" in comp:
				employee_data[emp]["nssf"] += d.amount
			elif "SHIF" in comp:
				employee_data[emp]["shif"] += d.amount
			elif "HOUSING LEVY" in comp:
				employee_data[emp]["housing_levy"] += d.amount

	return list(employee_data.values())

def get_conditions(filters):
	conditions = ""
	if filters.get("employee"):
		conditions += " AND employee = %(employee)s"
	if filters.get("from_date"):
		conditions += " AND start_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " AND end_date <= %(to_date)s"
	return conditions

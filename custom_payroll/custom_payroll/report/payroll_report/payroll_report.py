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
		{"fieldname": "pin", "label": _("PIN"), "fieldtype": "Data", "width": 120},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 150},
		{"fieldname": "resident_status", "label": _("Resident Status"), "fieldtype": "Data", "width": 120},
		{"fieldname": "type_of_employee", "label": _("Type of Employee"), "fieldtype": "Data", "width": 140},
		{"fieldname": "persons_with_disability", "label": _("Persons With Disability"), "fieldtype": "Data", "width": 150},
		{"fieldname": "exemption_certificate_number", "label": _("Exemption Certificate Number"), "fieldtype": "Data", "width": 180},
		{"fieldname": "total_cash_pay", "label": _("Total Cash Pay"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "car_benefit", "label": _("Value of Car Benefit"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "value_of_meals", "label": _("Value of Meals"), "fieldtype": "Currency", "options": "currency", "width": 120},
		{"fieldname": "non_cash_benefits", "label": _("Non Cash Benefits"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "type_of_housing", "label": _("Type of Housing"), "fieldtype": "Data", "width": 140},
		{"fieldname": "housing_benefit", "label": _("Housing Benefit"), "fieldtype": "Currency", "options": "currency", "width": 120},
		{"fieldname": "other_benefits", "label": _("Other Benefits"), "fieldtype": "Currency", "options": "currency", "width": 120},
		{"fieldname": "gross_pay", "label": _("Total Gross Pay (Ksh)"), "fieldtype": "Currency", "options": "currency", "width": 150},
		{"fieldname": "shif", "label": _("Social Health Insurance Fund (SHIF)"), "fieldtype": "Currency", "options": "currency", "width": 150},
		{"fieldname": "nssf", "label": _("NSSF Contribution"), "fieldtype": "Currency", "options": "currency", "width": 130},
		{"fieldname": "other_pension", "label": _("Other Pension Contribution"), "fieldtype": "Currency", "options": "currency", "width": 150},
		{"fieldname": "post_retirement_medical_fund", "label": _("Post Retirement Medical Fund"), "fieldtype": "Currency", "options": "currency", "width": 150},
		{"fieldname": "mortgage_interest", "label": _("Mortgage Interest"), "fieldtype": "Currency", "options": "currency", "width": 120},
		{"fieldname": "housing_levy", "label": _("Affordable Housing Levy"), "fieldtype": "Currency", "options": "currency", "width": 150},
		{"fieldname": "taxable_pay", "label": _("Taxable Pay (Ksh)"), "fieldtype": "Currency", "options": "currency", "width": 120},
		{"fieldname": "monthly_personal_relief", "label": _("Monthly Personal Relief (Ksh)"), "fieldtype": "Currency", "options": "currency", "width": 150},
		{"fieldname": "insurance_relief", "label": _("Amount of Insurance Relief (Ksh)"), "fieldtype": "Currency", "options": "currency", "width": 160},
		{"fieldname": "paye_tax", "label": _("PAYE Tax (Ksh)"), "fieldtype": "Currency", "options": "currency", "width": 120},
		{"fieldname": "paye", "label": _("Self Assessed PAYE Tax (Ksh)"), "fieldtype": "Currency", "options": "currency", "width": 160},
		{"fieldname": "currency", "label": _("Currency"), "fieldtype": "Data", "hidden": 1}
	]

def get_data(filters):
	conditions = get_conditions(filters)
	
	salary_slips = frappe.db.sql(f"""
		SELECT 
			s.name as slip_id,
			s.employee as payroll_id, 
			s.employee_name, 
			s.gross_pay, 
			s.net_pay,
			s.currency,
			e.custom_pin
		FROM `tabSalary Slip` s
		LEFT JOIN `tabEmployee` e ON s.employee = e.name
		WHERE s.docstatus = 1 {conditions}
	""", filters, as_dict=1)

	if not salary_slips:
		return []

	slip_names = [d.slip_id for d in salary_slips]
	
	# Fetch deductions
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

	# Fetch earnings
	earnings = frappe.db.sql("""
		SELECT 
			parent as slip_id, 
			salary_component, 
			amount 
		FROM `tabSalary Detail` 
		WHERE parentfield='earnings' 
			AND parenttype='Salary Slip'
			AND parent IN %s
	""", (tuple(slip_names),), as_dict=1)

	slip_earnings = {}
	for e in earnings:
		slip_earnings.setdefault(e.slip_id, []).append(e)

	employee_data = {}
	for slip in salary_slips:
		emp = slip.payroll_id
		if emp not in employee_data:
			employee_data[emp] = {
				"pin": slip.custom_pin or "0",
				"employee_name": slip.employee_name,
				"resident_status": "Resident",
				"type_of_employee": "Primary Employee",
				"persons_with_disability": "No",
				"exemption_certificate_number": "",
				"total_cash_pay": 0.0,
				"car_benefit": 0.0,
				"value_of_meals": 0.0,
				"non_cash_benefits": 0.0,
				"type_of_housing": "Benefit not given",
				"housing_benefit": 0.0,
				"other_benefits": 0.0,
				"gross_pay": 0.0,
				"shif": 0.0,
				"nssf": 0.0,
				"other_pension": 0.0,
				"post_retirement_medical_fund": 0.0,
				"mortgage_interest": 0.0,
				"housing_levy": 0.0,
				"taxable_pay": 0.0,
				"monthly_personal_relief": 2400.0,
				"insurance_relief": 0.0,
				"paye_tax": 0.0,
				"paye": 0.0,
				"currency": slip.currency
			}
		
		# Process Earnings for Housing Benefit and Adjustments
		has_accommodation = False
		housing_amt = 0.0
		other_benefits_amt = 0.0
		meals_amt = 0.0
		basic_pay_amt = 0.0
		
		for e in slip_earnings.get(slip.slip_id, []):
			comp = (e.salary_component or "").upper()
			if "ACCOMMODATION PROVIDED" in comp:
				has_accommodation = True
				housing_amt += e.amount
			elif "ADJUSTMENTS" in comp:
				other_benefits_amt += e.amount
			elif "MEALS PROVIDED" in comp:
				meals_amt += e.amount
			elif "BASIC PAY" in comp:
				basic_pay_amt += e.amount
				
		if has_accommodation:
			employee_data[emp]["type_of_housing"] = "Benefit given"
			employee_data[emp]["housing_benefit"] += housing_amt
			
		employee_data[emp]["other_benefits"] += other_benefits_amt
		employee_data[emp]["value_of_meals"] += meals_amt
		employee_data[emp]["total_cash_pay"] += basic_pay_amt

		# Process Deductions
		for d in slip_deductions.get(slip.slip_id, []):
			comp = (d.salary_component or "").upper()
			if "PAYE" in comp:
				employee_data[emp]["paye"] += d.amount
			elif "NSSF" in comp:
				employee_data[emp]["nssf"] += d.amount
			elif "SHIF" in comp or "SHA" in comp:
				employee_data[emp]["shif"] += d.amount
			elif "HOUSING LEVY" in comp:
				employee_data[emp]["housing_levy"] += d.amount

	# Apply Excel Formulas
	for emp_data in employee_data.values():
		# Total Gross Pay (H) = A + B + C + D + F + G
		emp_data["gross_pay"] = (
			emp_data["total_cash_pay"] + 
			emp_data["car_benefit"] + 
			emp_data["value_of_meals"] + 
			emp_data["non_cash_benefits"] + 
			emp_data["housing_benefit"] + 
			emp_data["other_benefits"]
		)
		
		# Taxable Pay (O) = H - (I+J Max 30k) - (K Max 15k) - (L Max 30k) - N
		ij_sum = min(emp_data["shif"] + emp_data["nssf"], 30000.0)
		k_val = min(emp_data["other_pension"], 15000.0)
		l_val = min(emp_data["post_retirement_medical_fund"], 30000.0)
		
		emp_data["taxable_pay"] = max(0.0, (
			emp_data["gross_pay"] - 
			ij_sum - 
			k_val - 
			l_val - 
			emp_data["housing_levy"]
		))
		
		# PAYE Tax (R) usually mirrors Self Assessed PAYE Tax (S)
		emp_data["paye_tax"] = emp_data["paye"]

	return list(employee_data.values())

def get_conditions(filters):
	conditions = ""
	if filters.get("employee"):
		conditions += " AND s.employee = %(employee)s"
	if filters.get("from_date"):
		conditions += " AND s.start_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " AND s.end_date <= %(to_date)s"
	return conditions

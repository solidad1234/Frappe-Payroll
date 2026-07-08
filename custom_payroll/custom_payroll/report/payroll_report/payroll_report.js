// Copyright (c) 2026, Solidad Kimeu and contributors
// For license information, please see license.txt

frappe.query_reports["Payroll Report"] = {
	"filters": [
		{
			"fieldname": "employee",
			"label": __("Employee"),
			"fieldtype": "Link",
			"options": "Employee"
		},
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": moment().subtract(1, 'months').startOf('month').format('YYYY-MM-DD'),
			"reqd": 1
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": moment().subtract(1, 'months').endOf('month').format('YYYY-MM-DD'),
			"reqd": 1
		}
	]
};

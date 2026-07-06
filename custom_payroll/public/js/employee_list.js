frappe.listview_settings['Employee'] = {
    onload(listview) {
        listview.page.add_button('Generate Payroll', function() {
            let d = new frappe.ui.Dialog({
                title: 'Generate Payroll',
                fields: [
                    {
                        label: 'From Date',
                        fieldname: 'from_date',
                        fieldtype: 'Date',
                        reqd: 1
                    },
                    {
                        label: 'To Date',
                        fieldname: 'to_date',
                        fieldtype: 'Date',
                        reqd: 1
                    }
                ],
                primary_action_label: 'Send',
                primary_action(values) {
                    if (!values.from_date || !values.to_date) {
                        frappe.throw('Please fill in all required fields.');
                    }

                    let selected_employees = listview.get_checked_items().map(row => row.name);

                    frappe.confirm(
                        selected_employees.length ?
                            `Are you sure you want to process payroll for ${selected_employees.length} employee(s)?` :
                            `No employees selected. Proceed with all employees to generate Payroll?`,
                        function() {
                            d.hide();

                            frappe.call({
                                method: 'custom_payroll.services.payroll.create_salary_slips',
                                args: {
                                    from_date: values.from_date,
                                    to_date: values.to_date,
                                    employee_ids: selected_employees.length ? selected_employees : null
                                },
                                callback(r) {
                                    // Optional: show a message or refresh
                                    frappe.msgprint(__('Payroll process initiated...   proceed to salary slip.'));
                                    // listview.refresh();
                                }
                            });
                        }
                    );
                }
            });
            d.show();
        });
    }
};

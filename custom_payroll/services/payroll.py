import frappe
from datetime import datetime
from frappe.utils import getdate
from frappe.utils import today, flt
from frappe.utils import nowdate
import urllib.parse


@frappe.whitelist(allow_guest=True)
def create_salary_slips(from_date, to_date, employee_ids=None):
    try:
        if employee_ids:
            if isinstance(employee_ids, str):
                import json
                employee_ids = json.loads(employee_ids)
            filters = {
                "name": ["in", employee_ids],
                "status": "Active",
            }
        else:
            filters = {
                "status": "Active",
            }

        employees = frappe.get_all("Employee", filters=filters, fields=["*"])
        settings = frappe.get_doc("Custom Payroll Settings")
        salary_structure = settings.default_salary_structure

        count = 0
        for employee in employees:
            frappe.enqueue(
                method=create_salary_slip,
                queue='long',
                timeout=300,
                employee_name=employee.name,
                base=employee.ctc,
                from_date=from_date,
                to_date=to_date,
                salary_structure=salary_structure
            )
            count += 1

        return f"{count} Salary Slip creation job{'s' if count != 1 else ''} queued successfully."

    except Exception as e:
        frappe.throw(f"Error creating salary slips: {str(e)}")


def safe_eval(expr, base):
    """
    Safely evaluate a formula/condition string.
    - Replaces 'base' with the actual value
    - Strips newlines and carriage returns that cause eval() syntax errors
    """
    cleaned = expr.replace("base", str(base)).replace("\n", " ").replace("\r", " ").strip()
    return eval(cleaned)


def create_salary_slip(employee_name, base, from_date, to_date, salary_structure):
    try:
        salary_components = frappe.get_all(
            "Salary Detail",
            filters={"parent": salary_structure, "docstatus": 1},
            fields=["*"]
        )

        penalty_amount = get_employee_penalty(employee_name)
        advance_amount = get_employee_advance(employee_name)
        sacco_saving = frappe.db.get_value("Employee", {"name": employee_name}, "custom_sacco_saving")
        adjustments = frappe.db.get_value("Employee", {"name": employee_name}, "custom_adjustments")
        sacco_addons = frappe.db.get_value("Employee", {"name": employee_name}, "custom_sacco_add_ons")
        house_allowance = frappe.db.get_value("Employee", {"name": employee_name}, "custom_house_allowance")
        meal_allowance = frappe.db.get_value("Employee", {"name": employee_name}, "custom_meal_allowance")

        deductions = []
        earnings = []

        for salary_component in salary_components:
            if salary_component.disabled == 1:
                continue

            if salary_component.amount_based_on_formula == 0:
                # Fixed amount component — skip if amount is negligible
                if salary_component.amount < 1:
                    continue

                condition = salary_component.condition
                if not condition or safe_eval(condition, base):
                    component_type = frappe.db.get_value(
                        "Salary Component", salary_component.salary_component, "type"
                    )
                    if component_type == "Earning":
                        if not any(e['salary_component'] == salary_component.salary_component for e in earnings):
                            earnings.append({
                                "salary_component": salary_component.salary_component,
                                "amount": salary_component.amount
                            })
                    elif component_type == "Deduction":
                        if not any(d['salary_component'] == salary_component.salary_component for d in deductions):
                            deductions.append({
                                "salary_component": salary_component.salary_component,
                                "amount": salary_component.amount
                            })
            else:
                # Formula-based component
                condition = salary_component.condition
                if not condition or safe_eval(condition, base):
                    formula = salary_component.formula
                    amount = safe_eval(formula, base)

                    # Floor to 0 — prevents ERPNext from overriding with 1.00
                    # e.g. PAYE after personal relief goes negative → stored as 0.00
                    amount = max(0, amount)
                    amount = round(amount, 2)

                    # Skip zero-amount formula components (e.g. PAYE = 0 after relief)
                    if amount == 0:
                        continue

                    component_type = frappe.db.get_value(
                        "Salary Component", salary_component.salary_component, "type"
                    )
                    if component_type == "Earning":
                        if not any(e['salary_component'] == salary_component.salary_component for e in earnings):
                            earnings.append({
                                "salary_component": salary_component.salary_component,
                                "amount": amount
                            })
                    elif component_type == "Deduction":
                        if not any(d['salary_component'] == salary_component.salary_component for d in deductions):
                            deductions.append({
                                "salary_component": salary_component.salary_component,
                                "amount": amount
                            })

        # Custom deductions
        if penalty_amount > 0:
            deductions.append({"salary_component": "Penalty", "amount": penalty_amount})
        if advance_amount > 0:
            deductions.append({"salary_component": "Advance", "amount": advance_amount})
        if sacco_saving > 0:
            deductions.append({"salary_component": "Sacco Saving", "amount": sacco_saving})

        # Custom non-taxable earnings — added AFTER deduction calculation
        # so they do NOT affect the base used for PAYE/NSSF/SHIF/Housing Levy
        if adjustments > 0:
            earnings.append({"salary_component": "Adjustments", "amount": adjustments})
        if sacco_addons > 0:
            earnings.append({"salary_component": "Sacco Add Ons", "amount": sacco_addons})
        if house_allowance > 0:
            earnings.append({"salary_component": "Accommodation Provided", "amount": house_allowance})
        if meal_allowance > 0:
            earnings.append({"salary_component": "Meals Provided", "amount": meal_allowance})

        # Create salary slip
        salary_slip = frappe.get_doc({
            "doctype": "Salary Slip",
            "employee": employee_name,
            "posting_date": datetime.now(),
            "payroll_frequency": "Monthly",
            "start_date": from_date,
            "end_date": to_date,
            "salary_structure": salary_structure,
            "earnings": earnings,
            "deductions": deductions
        })

        salary_slip.insert(ignore_mandatory=True, ignore_permissions=True)

        # Reload saved doc so child rows have their DB names
        # and we can sum reliably without ERPNext's recalculation overriding our values
        saved = frappe.get_doc("Salary Slip", salary_slip.name)

        gross_pay = sum(e.amount for e in saved.earnings)
        total_deduction = sum(d.amount for d in saved.deductions)
        net_pay = gross_pay - total_deduction

        frappe.db.set_value("Salary Slip", saved.name, {
            "base_gross_pay": gross_pay,
            "gross_pay": gross_pay,
            "total_deduction": total_deduction,
            "base_total_deduction": total_deduction,
            "base_net_pay": net_pay,
            "net_pay": net_pay,
            "rounded_total": round(net_pay),
            "base_rounded_total": round(net_pay)
        })

        frappe.db.commit()

        return salary_slip.name

    except Exception as e:
        frappe.throw(f"Error creating salary slip for {employee_name}: {str(e)}")


def salary_slip_after_insert(doc, event):
    """
    Hook: recalculate gross/net pay after insert to ensure
    all earnings (including non-taxable allowances) are included.
    ERPNext's internal calculate_net_pay only uses 'base', so we override here.
    """
    gross_pay = sum(e.amount for e in doc.earnings)
    total_deduction = sum(d.amount for d in doc.deductions)
    net_pay = gross_pay - total_deduction

    frappe.db.set_value("Salary Slip", doc.name, {
        "base_gross_pay": gross_pay,
        "gross_pay": gross_pay,
        "total_deduction": total_deduction,
        "base_total_deduction": total_deduction,
        "base_net_pay": net_pay,
        "net_pay": net_pay,
        "rounded_total": round(net_pay),
        "base_rounded_total": round(net_pay)
    })


def mark_penalties_paid(employee_name, salary_slip):
    try:
        penalties = frappe.db.get_all(
            "Employee Penalty",
            filters={"employee": employee_name, "status": "Unpaid", "docstatus": 1},
            fields=["name"]
        )
        for penalty in penalties:
            frappe.db.set_value("Employee Penalty", penalty.name, {
                "status": "Paid",
                "paid_on": datetime.now(),
                "reference_salary_slip": salary_slip
            })
        frappe.db.commit()
    except Exception as e:
        frappe.throw(f"Error marking penalties paid for {employee_name}: {str(e)}")


def get_salary_period_dates():
    current_date = datetime.now()
    current_year = current_date.year
    current_month = current_date.month

    if current_date.day >= 26:
        start_date = datetime(current_year, current_month - 1, 26)
        if current_month == 12:
            end_date = datetime(current_year + 1, 1, 25)
        else:
            end_date = datetime(current_year, current_month, 25)
    else:
        if current_month == 1:
            start_date = datetime(current_year - 1, 12, 26)
        else:
            start_date = datetime(current_year, current_month - 1, 26)
        end_date = datetime(current_year, current_month, 25)
    return start_date, end_date


@frappe.whitelist()
def get_employee_penalty(employee_name):
    employee_penalties = frappe.db.get_all(
        "Employee Penalty",
        filters={"employee": employee_name, "status": "Unpaid", "docstatus": 1},
        fields=["amount"]
    )
    total_penalty_amount = sum(penalty.amount for penalty in employee_penalties)
    return total_penalty_amount or 0


@frappe.whitelist()
def get_employee_advance(employee_name):
    try:
        employee_advance = frappe.db.get_value(
            "Employee Advance",
            {"employee": employee_name, "status": "Unpaid"},
            "custom_monthly_payment_amount"
        )
        return employee_advance or 0
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Employee Advance Error")
        return 0


def mark_advances_paid(employee_name):
    try:
        advances = frappe.db.get_all(
            "Employee Advance",
            filters={"employee": employee_name, "status": "Unpaid"},
            fields=["*"]
        )
        for advance in advances:
            total_paid_amount = advance.paid_amount + advance.custom_monthly_payment_amount
            frappe.db.set_value("Employee Advance", advance.name, {"paid_amount": total_paid_amount})
            if total_paid_amount >= advance.advance_amount:
                frappe.db.set_value("Employee Advance", advance.name, {"status": "Paid"})
        frappe.db.commit()
    except Exception as e:
        frappe.throw(f"Error marking advances paid for {employee_name}: {str(e)}")


@frappe.whitelist()
def create_employee_salary_structure_assignment(doc, event):
    try:
        from_date = frappe.db.get_value("Employee", doc.name, "date_of_joining")

        if not from_date:
            frappe.throw(f"Employee {doc.name} does not have a Date of Joining set.")

        create_salary_structure_assignment(doc.name, doc.ctc, from_date, doc.company)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f'Error creating salary structure assignment: {e}')
        return {"status": "Error creating salary structure assignment", "message": str(e)}


@frappe.whitelist()
def create_salary_structure_assignment(employee, base, from_date, company):
    try:
        # Fallback to Date of Joining if from_date is missing
        if not from_date:
            from_date = frappe.db.get_value("Employee", employee, "date_of_joining")
        
        # Final fallback to current date if joining date is also missing
        if not from_date:
            from_date = nowdate()

        frappe.log_error(
            "salary structure assignment parameters",
            f'Parameters: employee={employee}, base={base}, from_date={from_date}, company={company}'
        )

        settings = frappe.get_doc("Custom Payroll Settings")
        salary_structure = settings.default_salary_structure

        frappe.log_error(
            f'Selected salary structure: {salary_structure}',
            'Debugging create_salary_structure_assignment'
        )

        salary_structure_doc = frappe.get_doc({
            "doctype": "Salary Structure Assignment",
            "employee": employee,
            "salary_structure": salary_structure,
            "company": company,
            "from_date": from_date,
            "base": base
        })

        salary_structure_doc.insert()
        salary_structure_doc.submit()
        frappe.log_error(
            'Salary structure assignment created successfully',
            'Debugging create_salary_structure_assignment'
        )
        return {"status": "success"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f'Error creating salary structure assignment: {e}')
        return {"status": "Error creating salary structure assignment", "message": str(e)}


@frappe.whitelist(allow_guest=True)
def update_salary_structure_assignment(doc, event):
    try:
        salary_structure_assignment = frappe.db.exists(
            "Salary Structure Assignment", {"employee": doc.name, "docstatus": 1}
        )
        if salary_structure_assignment:
            salary_assignment = frappe.get_doc("Salary Structure Assignment", salary_structure_assignment)
            if salary_assignment.base != doc.ctc:
                frappe.db.set_value(
                    "Salary Structure Assignment",
                    {"employee": doc.name, "docstatus": 1},
                    "docstatus", 2
                )
                from_date = doc.date_of_joining
                create_salary_structure_assignment(doc.name, doc.ctc, from_date, doc.company)
        return {"status": "success"}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f'Error updating salary structure assignment: {e}')
        return {"status": "Error updating salary structure assignment", "message": str(e)}


@frappe.whitelist()
def create_journal_entry_for_salary_slip(doc, event):
    salary_slip_on_submit(doc)
    try:
        settings = frappe.get_doc("Custom Payroll Settings")
        mark_penalties_paid(doc.employee, doc.name)
        mark_advances_paid(doc.employee)

        salary_account = settings.salary_account

        jv = frappe.new_doc('Journal Entry')
        jv.voucher_type = 'Journal Entry'
        jv.naming_series = 'ACC-JV-.YYYY.-'
        jv.posting_date = today()
        jv.company = doc.company
        jv.remark = 'Salary Payment'
        jv.cheque_no = doc.name
        jv.cheque_date = today()
        jv.reference_document = "Salary Slip"
        jv.reference_name = doc.name

        total_deductions = 0
        salary_advance_amount = 0

        for deduction in doc.deductions:
            if deduction.salary_component == "Salary Advance":
                salary_advance_amount = deduction.amount
                break

        adjusted_gross_pay = doc.gross_pay - salary_advance_amount

        jv.append('accounts', {
            'account': salary_account,
            'credit': adjusted_gross_pay,
            'debit': 0,
            'credit_in_account_currency': adjusted_gross_pay,
            'debit_in_account_currency': 0,
        })

        for deduction in doc.deductions:
            if deduction.amount > 0 and deduction.salary_component != "Salary Advance":
                deduction_account = frappe.get_value(
                    'Salary Component Account',
                    {"parent": deduction.salary_component},
                    "account"
                )

                total_deductions += deduction.amount

                jv.append('accounts', {
                    'account': deduction_account,
                    'debit': deduction.amount,
                    'credit': 0,
                    'debit_in_account_currency': deduction.amount,
                    'credit_in_account_currency': 0,
                    'party_type': "Employee",
                    'party': doc.employee,
                })

        jv.append('accounts', {
            'account': settings.salary_expense_account,
            'debit': doc.net_pay,
            'credit': 0,
            'debit_in_account_currency': doc.net_pay,
            'credit_in_account_currency': 0,
            'party_type': "Employee",
            'party': doc.employee,
        })

        if total_deductions + doc.net_pay != adjusted_gross_pay:
            frappe.throw("Total debits do not match the adjusted gross pay.")

        jv.insert(ignore_permissions=True)
        jv.submit()

        return {"status": "success"}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f'Error creating journal entry: {e}')
        return {"status": "Error creating journal entry", "message": str(e)}


@frappe.whitelist()
def create_journal_entry_for_employee_advance(doc, event):
    settings = frappe.get_doc("Custom Payroll Settings")

    jv = frappe.new_doc('Journal Entry')
    jv.voucher_type = 'Journal Entry'
    jv.naming_series = 'ACC-JV-.YYYY.-'
    jv.posting_date = today()
    jv.company = frappe.defaults.get_user_default("Company")
    jv.remark = 'Employee Advance'
    jv.cheque_no = doc.name
    jv.cheque_date = today()

    jv.append('accounts', {
        'account': settings.advance_account,
        'credit': float(doc.advance_amount),
        'debit': float(0),
        'debit_in_account_currency': float(0),
        'credit_in_account_currency': float(doc.advance_amount),
    })

    jv.append('accounts', {
        'account': doc.advance_account,
        'debit': float(doc.advance_amount),
        'credit': float(0),
        'credit_in_account_currency': float(0),
        'debit_in_account_currency': float(doc.advance_amount),
        'party_type': "Employee",
        'party': doc.employee,
    })

    jv.insert(ignore_permissions=True)
    jv.submit()


@frappe.whitelist(allow_guest=True)
def assign_salary_structures_to_all_active_employees():
    """Enqueue the bulk assignment to avoid request timeout."""
    frappe.enqueue(
        _bulk_assign_salary_structures,
        queue="long",
        timeout=3600,
        job_name="bulk_salary_structure_assignment"
    )
    return {"status": "queued", "message": "Salary structure assignment has been queued. Check Error Log for results."}


def _bulk_assign_salary_structures():
    try:
        settings = frappe.get_doc("Custom Payroll Settings")
        default_salary_structure = settings.default_salary_structure
        default_company = frappe.db.get_single_value("Global Defaults", "default_company")

        employees = frappe.get_all(
            "Employee",
            filters={"status": "Active"},
            fields=["name", "ctc", "date_of_joining"]
        )

        created, skipped, cancelled = 0, 0, 0

        for emp in employees:
            if not emp.date_of_joining:
                frappe.log_error(
                    f"Employee {emp.name} has no Date of Joining, skipping",
                    "Salary Structure Assignment"
                )
                skipped += 1
                continue

            try:
                already_assigned = frappe.db.exists(
                    "Salary Structure Assignment",
                    {
                        "employee": emp.name,
                        "salary_structure": default_salary_structure,
                        "docstatus": 1
                    }
                )

                if already_assigned:
                    skipped += 1
                    continue

                other_assignments = frappe.get_all(
                    "Salary Structure Assignment",
                    filters={
                        "employee": emp.name,
                        "salary_structure": ["!=", default_salary_structure],
                        "docstatus": 1
                    },
                    fields=["name"]
                )

                for assignment in other_assignments:
                    doc = frappe.get_doc("Salary Structure Assignment", assignment.name)
                    doc.cancel()
                    cancelled += 1

                new_assignment = frappe.get_doc({
                    "doctype": "Salary Structure Assignment",
                    "employee": emp.name,
                    "salary_structure": default_salary_structure,
                    "company": default_company,
                    "from_date": emp.date_of_joining,
                    "base": emp.ctc
                })
                new_assignment.insert()
                new_assignment.submit()
                created += 1

            except Exception:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"Error processing salary structure for {emp.name}"
                )
                skipped += 1

        summary = (
            f"Bulk Salary Structure Assignment Complete: "
            f"{created} created, {cancelled} cancelled, {skipped} skipped."
        )
        frappe.log_error(summary, "Salary Structure Assignment Summary")

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Critical error in bulk salary structure assignment"
        )


@frappe.whitelist()
def post_payroll_journal_entry(from_date, to_date):
    try:
        settings = frappe.get_doc("Custom Payroll Settings")
        salary_account = settings.salary_account
        salary_expense_account = settings.salary_expense_account

        slips = frappe.get_all(
            "Salary Slip",
            filters={
                "docstatus": 1,
                "start_date": [">=", from_date],
                "end_date": ["<=", to_date],
            },
            fields=["name", "employee", "net_pay", "gross_pay"]
        )

        if not slips:
            frappe.throw("No submitted Salary Slips found for the selected period.")

        total_net_pay = 0
        total_gross_pay = 0

        for slip in slips:
            total_net_pay += slip.net_pay or 0
            total_gross_pay += slip.gross_pay or 0

        jv = frappe.new_doc('Journal Entry')
        jv.voucher_type = 'Journal Entry'
        jv.naming_series = 'ACC-JV-.YYYY.-'
        jv.posting_date = today()
        jv.company = frappe.db.get_single_value("Global Defaults", "default_company")
        jv.remark = f'Salary Payment for period {from_date} to {to_date}'
        jv.cheque_no = f"Payroll-{from_date}-to-{to_date}"
        jv.cheque_date = today()
        jv.reference_document = "Salary Slip"

        jv.append('accounts', {
            'account': salary_account,
            'credit': total_net_pay,
            'debit': 0,
            'credit_in_account_currency': total_net_pay,
            'debit_in_account_currency': 0,
        })

        jv.append('accounts', {
            'account': salary_expense_account,
            'debit': total_net_pay,
            'credit': 0,
            'debit_in_account_currency': total_net_pay,
            'credit_in_account_currency': 0,
        })

        jv.insert(ignore_permissions=True)
        jv.submit()

        return {
            "status": "success",
            "message": f"Posted journal entry {jv.name} for {len(slips)} salary slips, total {total_net_pay}"
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Error posting payroll journal entry")
        return {"status": "error", "message": str(e)}


from frappe import _


@frappe.whitelist(allow_guest=True)
def cancel_salary_slips_and_jvs():
    """
    Cancel all submitted Salary Slips and their linked Journal Entries.
    Runs in background for safety on large datasets.
    """
    frappe.enqueue(
        "fleet_management.services.payroll._cancel_salary_slips_and_jvs",
        queue="long",
        timeout=6000
    )
    return {"status": "queued"}


def _cancel_salary_slips_and_jvs():
    results = {"cancelled_slips": [], "cancelled_jvs": [], "errors": []}

    salary_slips = frappe.get_all("Salary Slip", filters={"docstatus": 1}, pluck="name")

    for slip_name in salary_slips:
        try:
            slip = frappe.get_doc("Salary Slip", slip_name)
            linked_jv = frappe.db.get_value(
                "Journal Entry Account",
                {"reference_name": slip.name, "reference_type": "Salary Slip"},
                "parent"
            )

            if linked_jv:
                try:
                    jv = frappe.get_doc("Journal Entry", linked_jv)
                    if jv.docstatus == 1:
                        jv.cancel()
                        results["cancelled_jvs"].append(jv.name)
                except Exception as e:
                    frappe.log_error(frappe.get_traceback(), f"Failed to cancel JV {linked_jv}")
                    results["errors"].append(
                        f"Failed to cancel Journal Entry {linked_jv} for {slip.name}: {e}"
                    )
                    continue

            if slip.docstatus == 1:
                slip.cancel()
                results["cancelled_slips"].append(slip.name)

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), f"Failed to cancel Salary Slip {slip_name}")
            results["errors"].append(
                f"Failed to cancel Salary Slip {slip_name}: {e}"
            )

    frappe.db.commit()
    return results

def salary_slip_on_submit(doc):
    """
    Hook: re-enforce correct gross/net pay on submit.
    ERPNext recalculates on submit using only 'base', overriding our
    pre-computed values that include non-taxable allowances.
    """
    gross_pay = sum(e.amount for e in doc.earnings)
    total_deduction = sum(d.amount for d in doc.deductions)
    net_pay = gross_pay - total_deduction

    frappe.db.set_value("Salary Slip", doc.name, {
        "base_gross_pay": gross_pay,
        "gross_pay": gross_pay,
        "total_deduction": total_deduction,
        "base_total_deduction": total_deduction,
        "base_net_pay": net_pay,
        "net_pay": net_pay,
        "rounded_total": round(net_pay),
        "base_rounded_total": round(net_pay)
    })

    frappe.db.commit()
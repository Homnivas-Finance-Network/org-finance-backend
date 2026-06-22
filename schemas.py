"""
Vertical field schemas for Homnivas Finance Network.

Each vertical (PL, BL, HL, LAP) defines an ordered list of sections, each
containing ordered fields. This single source of truth drives:
  1. The AI's data-capture checklist (what to ask the broker/client for)
  2. The structured-extraction contract (field keys the AI must use)
  3. The editable review form on the frontend
  4. The generated PDF infosheet layout

PL is the principal template (taken directly from the existing Homnivas
paper infosheet). BL, HL and LAP follow the same shape, adapted with the
field sets standard lenders/NBFCs in India request for those products.
"""

VERTICAL_NAMES = {
    "PL": "Personal Loan",
    "BL": "Business Loan",
    "HL": "Home Loan",
    "LAP": "Loan Against Property",
}

# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

def _loan_section():
    return ("Loan Requirement", [
        ("loan_amount_required", "Loan Amount Required"),
        ("loan_purpose", "Purpose of Loan"),
    ])


def _reference_sections():
    return [
        ("Reference 1 (Family/Relative)", [
            ("ref1_name", "Name"),
            ("ref1_relation", "Relation"),
            ("ref1_address", "Address"),
            ("ref1_pincode", "Pincode"),
            ("ref1_mobile", "Mobile Number"),
        ]),
        ("Reference 2 (Friend)", [
            ("ref2_name", "Name"),
            ("ref2_address", "Address"),
            ("ref2_pincode", "Pincode"),
            ("ref2_mobile", "Mobile Number"),
        ]),
    ]


# ---------------------------------------------------------------------------
# PL — Personal Loan (principal template, as supplied)
# ---------------------------------------------------------------------------

PL_SCHEMA = [
    _loan_section(),
    ("Personal Details", [
        ("name", "Name"),
        ("contact_no", "Contact No."),
        ("alternate_no", "Alternate No."),
        ("office_contact_no", "Office Contact No. (if Any)"),
        ("email_personal", "Email ID Personal"),
        ("email_official", "Email ID Official"),
        ("designation", "Designation in Current Company"),
        ("highest_education", "Highest Education"),
        ("marital_status", "Marital Status"),
        ("mother_name", "Mother Name"),
        ("spouse_name", "Spouse Name"),
        ("spouse_dob", "Spouse DOB"),
    ]),
    ("Employment & Residence", [
        ("work_experience_current_company", "Work Experience in Current Company"),
        ("total_work_experience", "Total Work Experience"),
        ("years_at_current_address", "Total No. Of Years at Current Address"),
        ("number_of_dependents", "Number of Dependents"),
        ("current_address_type", "Current Address Type (Owned/Rented)"),
        ("salary_account_opening_year", "Salary A/C Opening Year"),
    ]),
    ("Address", [
        ("permanent_address", "Permanent Address With Landmark and Pincode"),
        ("current_address", "Current Address With Landmark and Pincode"),
    ]),
    ("Company Details", [
        ("company_name", "Company Name"),
        ("company_address", "Company/Business Address with Pincode"),
    ]),
    *_reference_sections(),
]

# ---------------------------------------------------------------------------
# BL — Business Loan (researched: standard NBFC/bank BL intake fields)
# ---------------------------------------------------------------------------

BL_SCHEMA = [
    _loan_section(),
    ("Personal Details", [
        ("name", "Name"),
        ("contact_no", "Contact No."),
        ("alternate_no", "Alternate No."),
        ("email_personal", "Email ID Personal"),
        ("highest_education", "Highest Education"),
        ("marital_status", "Marital Status"),
        ("mother_name", "Mother Name"),
        ("spouse_name", "Spouse Name"),
        ("spouse_dob", "Spouse DOB"),
        ("number_of_dependents", "Number of Dependents"),
    ]),
    ("Residence", [
        ("permanent_address", "Permanent Address With Landmark and Pincode"),
        ("current_address", "Current Address With Landmark and Pincode"),
        ("current_address_type", "Current Address Type (Owned/Rented)"),
        ("years_at_current_address", "Total No. Of Years at Current Address"),
    ]),
    ("Business Details", [
        ("business_name", "Business/Firm Name"),
        ("business_constitution", "Constitution (Proprietorship/Partnership/Pvt Ltd/LLP)"),
        ("nature_of_business", "Nature of Business / Industry"),
        ("business_address", "Business Address with Pincode"),
        ("business_address_type", "Business Premises Type (Owned/Rented)"),
        ("business_vintage_years", "Years in Current Business (Vintage)"),
        ("gst_number", "GST Registration Number"),
        ("udyam_registration_no", "Udyam/MSME Registration No. (if any)"),
        ("business_pan", "PAN of Business/Firm"),
        ("annual_turnover", "Annual Turnover (Latest Year)"),
        ("itr_filed_last_2_years", "ITR Filed Last 2 Years (Yes/No)"),
        ("current_business_banker", "Current Business Banking With (Bank Name)"),
        ("existing_business_loan_emi", "Existing Business Loan/EMI (if any)"),
        ("number_of_employees", "Number of Employees"),
    ]),
    *_reference_sections(),
]

# ---------------------------------------------------------------------------
# HL — Home Loan (researched: standard HFC/bank HL intake fields)
# ---------------------------------------------------------------------------

HL_SCHEMA = [
    _loan_section(),
    ("Personal Details", [
        ("name", "Name"),
        ("contact_no", "Contact No."),
        ("alternate_no", "Alternate No."),
        ("office_contact_no", "Office Contact No. (if Any)"),
        ("email_personal", "Email ID Personal"),
        ("email_official", "Email ID Official"),
        ("designation", "Designation in Current Company"),
        ("highest_education", "Highest Education"),
        ("marital_status", "Marital Status"),
        ("mother_name", "Mother Name"),
        ("spouse_name", "Spouse Name"),
        ("spouse_dob", "Spouse DOB"),
    ]),
    ("Employment & Residence", [
        ("work_experience_current_company", "Work Experience in Current Company"),
        ("total_work_experience", "Total Work Experience"),
        ("years_at_current_address", "Total No. Of Years at Current Address"),
        ("number_of_dependents", "Number of Dependents"),
        ("current_address_type", "Current Address Type (Owned/Rented)"),
        ("salary_account_opening_year", "Salary A/C Opening Year"),
    ]),
    ("Address", [
        ("permanent_address", "Permanent Address With Landmark and Pincode"),
        ("current_address", "Current Address With Landmark and Pincode"),
    ]),
    ("Company Details", [
        ("company_name", "Company Name"),
        ("company_address", "Company/Business Address with Pincode"),
    ]),
    ("Property Details", [
        ("property_type", "Property Type (Flat/Independent House/Plot)"),
        ("property_stage", "Property Stage (Ready to Move/Under Construction/Resale)"),
        ("property_address", "Property Address With Landmark and Pincode"),
        ("builder_seller_name", "Builder/Seller Name"),
        ("agreement_value", "Agreement Value / Total Property Cost"),
        ("own_contribution", "Own Contribution / Down Payment Available"),
        ("expected_possession_year", "Expected Possession Year"),
        ("existing_home_loan", "Existing Home Loan (Yes/No)"),
        ("co_applicant_name", "Co-Applicant Name (if any)"),
        ("co_applicant_relation", "Co-Applicant Relation (if any)"),
    ]),
    *_reference_sections(),
]

# ---------------------------------------------------------------------------
# LAP — Loan Against Property (researched: standard LAP intake fields)
# ---------------------------------------------------------------------------

LAP_SCHEMA = [
    _loan_section(),
    ("Personal Details", [
        ("name", "Name"),
        ("contact_no", "Contact No."),
        ("alternate_no", "Alternate No."),
        ("email_personal", "Email ID Personal"),
        ("email_official", "Email ID Official"),
        ("highest_education", "Highest Education"),
        ("marital_status", "Marital Status"),
        ("mother_name", "Mother Name"),
        ("spouse_name", "Spouse Name"),
        ("spouse_dob", "Spouse DOB"),
        ("number_of_dependents", "Number of Dependents"),
    ]),
    ("Residence", [
        ("permanent_address", "Permanent Address With Landmark and Pincode"),
        ("current_address", "Current Address With Landmark and Pincode"),
        ("current_address_type", "Current Address Type (Owned/Rented)"),
        ("years_at_current_address", "Total No. Of Years at Current Address"),
    ]),
    ("Income Source", [
        ("income_source", "Income Source (Salaried/Self-Employed/Business)"),
        ("company_or_business_name", "Company / Business Name"),
        ("designation_or_business_type", "Designation / Nature of Business"),
        ("annual_income_turnover", "Annual Income / Turnover"),
    ]),
    ("Property (Collateral) Details", [
        ("property_type", "Property Type (Residential/Commercial/Industrial)"),
        ("property_address", "Property Address With Landmark and Pincode"),
        ("property_ownership", "Property Ownership (Self/Co-owned/Family)"),
        ("property_market_value", "Approx. Market Value of Property"),
        ("existing_loan_on_property", "Existing Loan on This Property (Yes/No)"),
        ("existing_loan_outstanding_amount", "Outstanding Amount (if any)"),
    ]),
    *_reference_sections(),
]

FIELD_SCHEMAS = {
    "PL": PL_SCHEMA,
    "BL": BL_SCHEMA,
    "HL": HL_SCHEMA,
    "LAP": LAP_SCHEMA,
}


def flat_fields(vertical: str):
    """Return [(key, label, section_title), ...] for a vertical, flattened."""
    schema = FIELD_SCHEMAS.get(vertical, [])
    out = []
    for section_title, fields in schema:
        for key, label in fields:
            out.append((key, label, section_title))
    return out


def valid_keys(vertical: str):
    return {key for key, _, _ in flat_fields(vertical)}


def progress(vertical: str, data: dict):
    keys = valid_keys(vertical)
    total = len(keys)
    filled = sum(1 for k in keys if str(data.get(k, "")).strip())
    percent = round((filled / total) * 100) if total else 0
    return {"filled": filled, "total": total, "percent": percent}

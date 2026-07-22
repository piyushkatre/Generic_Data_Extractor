import pytest
from modules.gemini import CanonicalFranchiseRecord
from modules.dataset_builder.record_validator import RecordValidator

def test_record_validator_franchise_name():
    # Valid name
    rec1 = CanonicalFranchiseRecord(franchise_name="Beatbox Gym")
    val1 = RecordValidator.validate_record(rec1)
    assert val1.franchise_name == "Beatbox Gym"

    # Generic placeholder
    rec2 = CanonicalFranchiseRecord(franchise_name="Franchise Opportunity")
    val2 = RecordValidator.validate_record(rec2)
    assert val2.franchise_name is None

def test_record_validator_established_year():
    # Valid year in text
    rec1 = CanonicalFranchiseRecord(established_year="Established in 2016")
    val1 = RecordValidator.validate_record(rec1)
    assert val1.established_year == "2016"

    # Invalid year string
    rec2 = CanonicalFranchiseRecord(established_year="Not Revealed")
    val2 = RecordValidator.validate_record(rec2)
    assert val2.established_year is None

def test_record_validator_agreement_duration():
    # Valid duration
    rec1 = CanonicalFranchiseRecord(agreement_duration="5 Years")
    val1 = RecordValidator.validate_record(rec1)
    assert val1.agreement_duration == "5"

    # Yes/No placeholder
    rec2 = CanonicalFranchiseRecord(agreement_duration="Yes")
    val2 = RecordValidator.validate_record(rec2)
    assert val2.agreement_duration is None

def test_record_validator_phone():
    # Valid phone
    rec1 = CanonicalFranchiseRecord(phone="+91 99999-88888")
    val1 = RecordValidator.validate_record(rec1)
    assert val1.phone == "+91 99999-88888"

    # Area range matching phone pattern
    rec2 = CanonicalFranchiseRecord(phone="3000 - 5000")
    val2 = RecordValidator.validate_record(rec2)
    assert val2.phone is None

def test_record_validator_email():
    # Valid email
    rec1 = CanonicalFranchiseRecord(email="contact@beatboxgym.com")
    val1 = RecordValidator.validate_record(rec1)
    assert val1.email == "contact@beatboxgym.com"

    # Invalid email
    rec2 = CanonicalFranchiseRecord(email="invalid_email")
    val2 = RecordValidator.validate_record(rec2)
    assert val2.email is None

def test_record_validator_roi():
    # Valid ROI
    rec1 = CanonicalFranchiseRecord(roi="30% - 40%")
    val1 = RecordValidator.validate_record(rec1)
    assert val1.roi == "30 - 40"

    # Invalid ROI
    rec2 = CanonicalFranchiseRecord(roi="High Return")
    val2 = RecordValidator.validate_record(rec2)
    assert val2.roi is None

def test_record_validator_investment():
    # Valid investment formatted to standard INR Lakhs/Crore
    rec1 = CanonicalFranchiseRecord(investment_required="Rs. 15Lakhs - 20Lakhs")
    val1 = RecordValidator.validate_record(rec1)
    assert val1.investment_required == "₹15 Lakhs - ₹20 Lakhs"

    # Invalid investment
    rec2 = CanonicalFranchiseRecord(investment_required="Moderate")
    val2 = RecordValidator.validate_record(rec2)
    assert val2.investment_required is None

def test_record_validator_area():
    # Valid area formatted to standard Sq.ft unit
    rec1 = CanonicalFranchiseRecord(area_required="3000 - 5000 Sq.ft")
    val1 = RecordValidator.validate_record(rec1)
    assert val1.area_required == "3000-5000 Sq.ft"

    # Invalid area
    rec2 = CanonicalFranchiseRecord(area_required="Spacious Room")
    val2 = RecordValidator.validate_record(rec2)
    assert val2.area_required is None

def test_record_validator_numeric_derivations():
    # Check derived fields functionality
    rec = CanonicalFranchiseRecord(
        investment_required="₹15 Lakhs - ₹20 Lakhs",
        area_required="3000-5000 Sq.ft"
    )
    val = RecordValidator.derive_numeric_ranges(rec)
    assert val.investment_min == 1500000
    assert val.investment_max == 2000000
    assert val.area_min == 3000
    assert val.area_max == 5000

def test_record_validator_comma_separated_phones():
    # Multiple valid phones
    rec = CanonicalFranchiseRecord(phone="+91 99999-88888, +91-88888-77777")
    val = RecordValidator.validate_record(rec)
    assert val.phone == "+91 99999-88888, +91-88888-77777"

    # Mixed valid/invalid
    rec2 = CanonicalFranchiseRecord(phone="+91 99999-88888, short, +91-11111-22222")
    val2 = RecordValidator.validate_record(rec2)
    assert val2.phone == "+91 99999-88888, +91-11111-22222"

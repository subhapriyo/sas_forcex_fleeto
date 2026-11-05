"""
Anonymised copy of the Konnect "Customer Invoice Line Report" (31-Oct-2026).

Names, phone numbers and addresses are fake, but every *data quirk* of the
real export is preserved on purpose, because the parser must survive them:

    row 0  clean 14-char chassis, 6 battery serials, typed numbers
    row 1  17-char chassis that contains the letter "O" (VINs never do)
    row 2  invoice date (28/9) earlier than Konnect date (9/10)
    row 3  WhatsApp number blank -> fall back to mobile
    row 4  obvious test/junk row (mobile 1234567890, garbage serials)
    row 5  "NA" in Volt / Ah, controller prefix "CTN" instead of "CNT"
    row 6  GST that does not add up (should be flagged)
    row 7  blank line (export padding) -> ignored
"""

HEADER = [
    "Bill From Party Code", "Bill From Party Name", "Customer Name",
    "Mobile Number", "WhatsApp No", "Email Address", "Invoice Date",
    "Address", "State", "District", "PIN", "Sex", "Age Group",
    "Employment Status", "Showroom Invoice Number", "Billing Type",
    "Konnect Invoice Number", "Konnect Invoice Date", "Model",
    "Product Name", "Colour", "Battery Type", "Volt", "Ah", "Quantity",
    "Unit Rate", "Total Item Value Without GST", "CGST", "SGST", "IGST",
    "Total Item Value With GST", "Chassis", "Motor", "Controller",
    "Charger", "IOT", "Battery1", "Battery2", "Battery3", "Battery4",
    "Battery5", "Battery6",
]


def _row(**kw):
    """Build one row in HEADER order; unspecified columns are ''."""
    base = dict.fromkeys(HEADER, "")
    base.update(kw)
    return [base[h] for h in HEADER]


ROWS = [
    _row(**{
        "Bill From Party Code": "DL-00381", "Bill From Party Name": "Demo Motors",
        "Customer Name": "Asha Roy", "Mobile Number": "8910000001",
        "WhatsApp No": "8910000001", "Invoice Date": "24/10/2026",
        "State": "West Bengal", "District": "Murshidabad", "PIN": "700001",
        "Billing Type": "Tertiary", "Konnect Invoice Number": "TINV0018",
        "Konnect Invoice Date": "24/10/2026", "Model": "Magnum",
        "Product Name": "Magnum LED 72V-46AH-1210-MBK", "Colour": "METALLIC BLACK",
        "Battery Type": "LED", "Volt": "NA", "Ah": "NA", "Quantity": 1,
        "Unit Rate": 66666.66, "Total Item Value Without GST": 66666.66,
        "CGST": 1666.67, "SGST": 1666.66, "IGST": 0,
        "Total Item Value With GST": 69999.99, "Chassis": "MD9EV2WL012345",
        "Motor": "FLEETO26MTR1234", "Controller": "FLEETO26CNT1234",
        "Charger": "FLW0012", "Battery1": "123456", "Battery2": "789123",
        "Battery3": "456123", "Battery4": "123567", "Battery5": "987654",
        "Battery6": "654321",
    }),
    _row(**{
        "Bill From Party Code": "DL-00363", "Bill From Party Name": "Demo Green Wheel",
        "Customer Name": "Bimal Patra", "Mobile Number": "8436000002",
        "WhatsApp No": "8436000002", "Invoice Date": "29/10/2026",
        "Konnect Invoice Number": "TINV0017", "Konnect Invoice Date": "9/10/2026",
        "Model": "Wolf Warrior", "Battery Type": "LED", "Quantity": 1,
        "Total Item Value Without GST": 45714.29, "CGST": 1142.86,
        "SGST": 1142.85, "IGST": 0, "Total Item Value With GST": 48000,
        "Chassis": "MD9ZX2WLO25669553", "Motor": "MTR9438",
        "Controller": "CTN10210", "Charger": "2507568",
    }),
    _row(**{
        "Bill From Party Code": "DL-00363", "Bill From Party Name": "Demo Green Wheel",
        "Customer Name": "Chandana Majhi", "Mobile Number": "9733000003",
        "WhatsApp No": "9733000003", "Invoice Date": "28/9/2026",
        "Konnect Invoice Number": "TINV0016", "Konnect Invoice Date": "9/10/2026",
        "Model": "Wolf Warrior", "Battery Type": "LED", "Quantity": 1,
        "Total Item Value Without GST": 51904.76, "CGST": 1297.62,
        "SGST": 1297.62, "IGST": 0, "Total Item Value With GST": 54500,
        "Chassis": "MD9ZX2WL025669435", "Motor": "MTR9442",
        "Controller": "CNT10152", "Charger": "07658",
    }),
    _row(**{
        "Bill From Party Code": "DL-00363", "Bill From Party Name": "Demo Green Wheel",
        "Customer Name": "Dipak Mondal", "Mobile Number": "8158000004",
        "WhatsApp No": "", "Invoice Date": "5/10/2026",
        "Konnect Invoice Number": "TINV0009", "Konnect Invoice Date": "9/10/2026",
        "Model": "Wolf Warrior", "Battery Type": "LED", "Quantity": 1,
        "Total Item Value Without GST": 51904.76, "CGST": 1297.62,
        "SGST": 1297.62, "IGST": 0, "Total Item Value With GST": 54500,
        "Chassis": "MD9ZX2WL025669091", "Motor": "MTR9677",
        "Controller": "CNT10380", "Charger": "1709202507597",
    }),
    _row(**{
        "Bill From Party Code": "DL-00377", "Bill From Party Name": "Demo Services",
        "Customer Name": "sdas", "Mobile Number": "1234567890",
        "WhatsApp No": "1234567890", "Invoice Date": "7/10/2026",
        "Konnect Invoice Number": "TINV0006", "Konnect Invoice Date": "7/10/2026",
        "Model": "Wolf", "Battery Type": "WTBT", "Quantity": 1,
        "Total Item Value Without GST": 28333.33, "CGST": 708.34,
        "SGST": 708.33, "IGST": 0, "Total Item Value With GST": 29750,
        "Chassis": "xzczxc", "Motor": "xzc", "Controller": "xzc",
        "Charger": "zxcxzc", "IOT": "zxczxc",
    }),
    _row(**{
        "Bill From Party Code": "DL-00363", "Bill From Party Name": "Demo Green Wheel",
        "Customer Name": "Esha Shit", "Mobile Number": "8900000006",
        "WhatsApp No": "8900000006", "Invoice Date": "25/9/2026",
        "Konnect Invoice Number": "TINV0012", "Konnect Invoice Date": "9/10/2026",
        "Model": "Magnum", "Battery Type": "LED", "Volt": "NA", "Ah": "NA",
        "Quantity": 1, "Total Item Value Without GST": 57142.86,
        "CGST": 1428.57, "SGST": 1428.57, "IGST": 0,
        "Total Item Value With GST": 60000, "Chassis": "MD9ZX2WL025668215",
        "Motor": "MTR8638", "Controller": "CTN09192", "Charger": "FLT60V4A05272",
    }),
    _row(**{
        "Bill From Party Code": "DL-00363", "Bill From Party Name": "Demo Green Wheel",
        "Customer Name": "Faruk Sahis", "Mobile Number": "+91 74300 00007",
        "WhatsApp No": "7430000007", "Invoice Date": "1/10/2026",
        "Konnect Invoice Number": "TINV0007", "Konnect Invoice Date": "9/10/2026",
        "Model": "Magnum", "Battery Type": "LED", "Quantity": 1,
        "Total Item Value Without GST": 63333.33, "CGST": 1583.34,
        "SGST": 1583.33, "IGST": 0, "Total Item Value With GST": 70000,
        "Chassis": "MD9ZX2WL025668508", "Motor": "MTR8779",
        "Controller": "CNT09133", "Charger": "6669",
    }),
    [None] * len(HEADER),
]

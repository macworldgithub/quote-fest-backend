import base64
import io
import uuid
import datetime
import csv
from typing import List, Dict, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import uvicorn
from openai import OpenAI
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm
from dotenv import load_dotenv
import os

load_dotenv()
XAI_API_KEY = os.getenv("XAI_API_KEY")
print(XAI_API_KEY)
if not XAI_API_KEY:
    raise ValueError("Please set XAI_API_KEY in .env or environment")
# ==================== CONFIGURATION ====================
client = OpenAI(base_url="https://api.x.ai/v1", api_key=XAI_API_KEY)

app = FastAPI(title="QUOTEFAST PRO v3.0", version="3.0")

# In-memory storage (replace with MongoDB later)
quotes_db: Dict[str, dict] = {}

# ==================== CATALOGUE ====================
CATALOGUE = {
    "mobile_plans": {
        "10Gb": 27, "15Gb": 32, "29Gb": 37, "40Gb": 44, "65Gb": 50,
        "100Gb": 55, "120Gb": 62, "150Gb": 71, "180Gb": 76
    },
    "nbn_plans": {
        "12/1Mbps": 60, "25/10Mbps": 60, "50/20Mbps": 90,
        "100/20Mbps": 95, "500/50Mbps": 100, "100/40Mbps": 100,
        "1000/100Mbps": 120, "2000/200Mbps": 200
    },
    "gold_bundles": {
        "Gold 500/200": 135, "Gold 1000/400": 160, "Gold 2000/500": 235
    },
    "pbx": {"PAYG": 10, "Unlimited": 30},
}

# ==================== PROMPT FOR GROK ====================
GROK_ANALYSIS_PROMPT = """
You are an expert Australian telco bill analyst. Analyze the uploaded bill (image or PDF pages).

Extract EXACTLY this JSON structure:

{
  "customer": {
    "type": "Business" or "Residential",
    "company": "Company Name" or null,
    "abn": "ABN" or null,
    "site_address": "Full site address",
    "billing_address": "Full billing address or same as site",
    "authorised_name": "Name",
    "authorised_phone": "Phone",
    "authorised_email": "Email",
    "dids": ["list of phone numbers"]
  },
  "current_services": {
    "mobiles": [{"plan": "100Gb", "quantity": 5, "monthly_ex": 55}],
    "nbn": {"plan": "100/40Mbps", "monthly_ex": 100} or null,
    "pbx_seats": 12 or null,
    "pbx_plan": "Unlimited" or "PAYG" or null,
    "other_recurring_ex": 0.0,
    "current_total_monthly_ex": 850.00
  },
  "recommendations": [
    {
      "name": "Best Value Bundle",
      "description": "Gold 500/200 Bundle + Unlimited PBX + keep mobiles",
      "new_monthly_ex": 635.00,
      "monthly_saving_ex": 215.00,
      "items": [
        {"sku": "BUNDLE-G500", "desc": "Gold 500/200 Bundle (incl NBN)", "qty": 1, "unit_ex": 135, "cadence": "monthly"},
        {"sku": "PBX-UNL", "desc": "Unlimited PBX Seat", "qty": 12, "unit_ex": 30, "cadence": "monthly"},
        {"sku": "MOB-100GB", "desc": "100Gb Mobile Plan", "qty": 5, "unit_ex": 55, "cadence": "monthly"}
      ]
    }
  ]
}

Prioritize plans that beat current spend. Use Gold bundles where possible (NBN becomes $0).
Only include visible data. Output valid JSON only.
"""

# ==================== MODELS ====================
class QuoteLine(BaseModel):
    sku: str
    desc: str
    qty: int
    unit_ex: float
    cadence: str  # monthly or once-off
    haas_term: Optional[int] = None

class QuoteResponse(BaseModel):
    id: str
    created: str
    customer: dict
    current_spend_ex: float
    recommendations: list
    selected_recommendation_index: int = 0
    lines: List[QuoteLine]
    ad_hoc_lines: List[QuoteLine] = []

# ==================== HELPER FUNCTIONS ====================
def encode_image(file_bytes: bytes) -> str:
    return base64.b64encode(file_bytes).decode("utf-8")

def call_grok_vision(image_base64: str):
    response = client.chat.completions.create(
        model="grok-4",
        messages=[
            {"role": "system", "content": GROK_ANALYSIS_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyze this telco bill."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            }
        ],
        response_format={"type": "json_object"},
        max_tokens=2000
    )
    try:
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Grok parsing failed: {str(e)}")

def generate_pdf(quote: dict) -> str:
    pdf_path = f"/tmp/{quote['id']}.pdf"
    doc = SimpleDocTemplate(pdf_path, pagesize=A4, topMargin=20*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='TitleBig', fontSize=24, leading=28, alignment=1))
    styles.add(ParagraphStyle(name='Saving', fontSize=18, textColor=colors.green))

    story = []

    story.append(Paragraph("QUOTEFAST PRO", styles['TitleBig']))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Date: {datetime.datetime.now().strftime('%d %B %Y')}", styles['Normal']))
    story.append(Paragraph(f"Quote ID: {quote['id'][:8]}", styles['Normal']))
    story.append(Spacer(1, 20))

    # Customer
    story.append(Paragraph("<b>Customer Details</b>", styles['Heading2']))
    story.append(Paragraph(f"{quote['customer'].get('company', 'Residential Customer')}", styles['Normal']))
    story.append(Paragraph(quote['customer']['site_address'], styles['Normal']))
    story.append(Paragraph(f"Contact: {quote['customer'].get('authorised_name', '')} – {quote['customer'].get('authorised_email', '')}", styles['Normal']))
    story.append(Spacer(1, 20))

    # Savings Table
    data = [
        ["", "Current Bill", "New Quote", "You Save"],
        ["Monthly Recurring (ex GST)", f"${quote['current_spend_ex']:.2f}", f"${quote['new_monthly_ex']:.2f}", f"${quote['monthly_saving_ex']:.2f}"],
        ["Monthly Saving", "", "", f"${quote['monthly_saving_ex']:.2f}"],
        ["Annual Saving", "", "", f"${quote['monthly_saving_ex']*12:.2f}"]
    ]
    table = Table(data, colWidths=[180, 100, 100, 100])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 14),
        ('BACKGROUND', (0,3), (-1,3), colors.lightgreen),
        ('TEXTCOLOR', (0,3), (-1,3), colors.darkgreen),
    ]))
    story.append(table)
    story.append(Spacer(1, 20))

    # Line Items
    story.append(Paragraph("<b>Recommended Solution</b>", styles['Heading2']))
    line_data = [["Qty", "Description", "Unit (ex GST)", "Total (ex GST)"]]
    total = 0
    for line in quote['lines'] + quote.get('ad_hoc_lines', []):
        if line['cadence'] == 'monthly':
            line_total = line['qty'] * line['unit_ex']
            total += line_total
            line_data.append([str(line['qty']), line['desc'], f"${line['unit_ex']:.2f}", f"${line_total:.2f}"])
    line_data.append(["", "", "Total Monthly (ex GST)", f"${total:.2f}"])

    item_table = Table(line_data, colWidths=[50, 300, 100, 100])
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
        ('ALIGN', (2,1), (-1,-1), 'RIGHT'),
    ]))
    story.append(item_table)
    story.append(Spacer(1, 30))

    story.append(Paragraph("Terms & Conditions attached. Valid for 30 days.", styles['Normal']))
    story.append(Paragraph("Contact your rep for any adjustments.", styles['Normal']))

    doc.build(story)
    return pdf_path

# ==================== API ENDPOINTS ====================
@app.post("/analyze-bill", response_model=QuoteResponse)
async def analyze_bill(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/") and file.content_type != "application/pdf":
        raise HTTPException(400, detail="Only image or PDF allowed")

    contents = await file.read()
    base64_image = encode_image(contents)

    try:
        analysis = call_grok_vision(base64_image)
    except Exception as e:
        raise HTTPException(500, detail=str(e))

    if not analysis.get("recommendations"):
        raise HTTPException(500, detail="No recommendations from Grok")

    selected_rec = analysis["recommendations"][0]
    quote_id = str(uuid.uuid4())

    quote = {
        "id": quote_id,
        "created": datetime.datetime.now().isoformat(),
        "customer": analysis["customer"],
        "current_spend_ex": analysis["current_services"]["current_total_monthly_ex"],
        "recommendations": analysis["recommendations"],
        "selected_recommendation_index": 0,
        "lines": selected_rec["items"],
        "ad_hoc_lines": [],
        "new_monthly_ex": selected_rec["new_monthly_ex"],
        "monthly_saving_ex": selected_rec["monthly_saving_ex"],
    }

    quotes_db[quote_id] = quote
    return quote

@app.post("/select-recommendation/{quote_id}")
async def select_recommendation(quote_id: str, index: int = Form(...)):
    quote = quotes_db.get(quote_id)
    if not quote or index >= len(quote["recommendations"]):
        raise HTTPException(404, "Invalid quote or index")
    rec = quote["recommendations"][index]
    quote["lines"] = rec["items"]
    quote["new_monthly_ex"] = rec["new_monthly_ex"]
    quote["monthly_saving_ex"] = rec["monthly_saving_ex"]
    quote["selected_recommendation_index"] = index
    return quote

@app.post("/add-adhoc/{quote_id}")
async def add_adhoc(quote_id: str, desc: str = Form(...), qty: int = Form(1), unit_ex: float = Form(...), cadence: str = Form("once-off")):
    quote = quotes_db.get(quote_id)
    if not quote:
        raise HTTPException(404)
    new_line = QuoteLine(sku="ADHOC", desc=desc, qty=qty, unit_ex=unit_ex, cadence=cadence).dict()
    quote["ad_hoc_lines"].append(new_line)
    return quote

@app.get("/quote/{quote_id}")
async def get_quote(quote_id: str):
    quote = quotes_db.get(quote_id)
    if not quote:
        raise HTTPException(404)
    return quote

@app.get("/pdf/{quote_id}")
async def get_pdf(quote_id: str):
    quote = quotes_db.get(quote_id)
    if not quote:
        raise HTTPException(404)
    pdf_path = generate_pdf(quote)
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"Quote_{quote_id[:8]}.pdf")

@app.get("/csv/{quote_id}")
async def get_csv(quote_id: str):
    quote = quotes_db.get(quote_id)
    if not quote:
        raise HTTPException(404)
    csv_path = f"/tmp/{quote_id}.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["SKU", "Description", "Quantity", "Unit ex-GST", "GST", "Cadence", "HaaS term"])
        for line in quote["lines"] + quote.get("ad_hoc_lines", []):
            writer.writerow([
                line["sku"], line["desc"], line["qty"], line["unit_ex"],
                "10%", line["cadence"], line.get("haas_term", "")
            ])
    return FileResponse(csv_path, media_type="text/csv", filename=f"Halo_Import_{quote_id[:8]}.csv")

@app.get("/")
async def root():
    return {"message": "QUOTEFAST PRO API Running – Upload bill at /analyze-bill"}

# ==================== RUN ====================
if __name__ == "__main__":
    uvicorn.run("quotefast:app", host="0.0.0.0", port=8001, reload=True)
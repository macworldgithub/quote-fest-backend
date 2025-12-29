# import base64
# import uuid
# import datetime
# import csv
# import os
# import tempfile
# import io
# import json
# from typing import List, Dict, Optional

# import fitz  # PyMuPDF
# from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
# from fastapi.responses import FileResponse
# from pydantic import BaseModel
# import uvicorn

# # If using the official OpenAI library with an XAI base_url:
# from openai import OpenAI

# from reportlab.lib.pagesizes import A4
# from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
# from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
# from reportlab.lib import colors
# from reportlab.lib.units import mm

# from dotenv import load_dotenv

# # OCR & image helpers
# from PIL import Image

# try:
#     import pytesseract
#     OCR_AVAILABLE = True
# except Exception:  # pylint: disable=broad-except
#     OCR_AVAILABLE = False

# # ==================== SETUP ====================
# load_dotenv()

# XAI_API_KEY = os.getenv("XAI_API_KEY")
# if not XAI_API_KEY:
#     raise ValueError("Set XAI_API_KEY in .env")

# # X.ai / XAI-compatible endpoint
# client = OpenAI(base_url="https://api.x.ai/v1", api_key=XAI_API_KEY)

# app = FastAPI(title="QUOTEFAST PRO v3.0 (OCR + Grok)")

# quotes_db: Dict[str, dict] = {}

# TEMP_DIR = tempfile.gettempdir()

# # ==================== FLEXIBLE PROMPT (No Static Structure) ====================
# GROK_PROMPT = """You are an expert Australian telco bill analyst. Analyze the full uploaded bill (all pages). Extract all relevant customer details, current services, spend, and anything useful. Then, recommend 1-3 superior plans from our catalogue that beat the current bill (lower cost or better value). Use Gold bundles where possible (NBN $0 in bundle). Output ONLY valid JSON. Use whatever structure makes the most sense for this specific bill. Include at minimum: - customer info (company, contacts, address, DIDs, etc.) - current monthly spend (ex GST) - recommendations with name, description, new monthly spend, saving, and line items (sku, desc, qty, unit_ex, cadence) Be creative with the structure if the bill has unusual sections — just make sure it's valid JSON that captures everything accurately."""

# # ==================== MODELS (Minimal – Flexible) ====================
# class QuoteLine(BaseModel):
#     sku: Optional[str] = "CUSTOM"
#     desc: str
#     qty: int = 1
#     unit_ex: float
#     cadence: str = "monthly"
#     haas_term: Optional[int] = None

# class QuoteResponse(BaseModel):
#     id: str
#     created: str
#     raw_grok_output: dict  # Whatever Grok gave us
#     customer: dict
#     current_spend_ex: float
#     recommendations: list
#     selected_lines: List[QuoteLine]
#     new_monthly_ex: float
#     monthly_saving_ex: float

# # ==================== OCR & TEXT EXTRACTION ====================
# def ocr_image_bytes(img_bytes: bytes, lang: str = "eng") -> str:
#     if not OCR_AVAILABLE:
#         return ""
#     img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
#     try:
#         return pytesseract.image_to_string(img, lang=lang)
#     except Exception:  # fallback to basic config if lang not available
#         return pytesseract.image_to_string(img)

# def pdf_extract_text(pdf_bytes: bytes, max_pages: Optional[int] = None, ocr_lang: str = "eng") -> str:
#     """Extract text from a PDF: native text first, fallback to OCR."""
#     doc = fitz.open(stream=pdf_bytes, filetype="pdf")
#     texts: List[str] = []
#     page_count = len(doc)
#     to_process = range(page_count) if max_pages is None else range(min(page_count, max_pages))

#     for i in to_process:
#         page = doc[i]
#         page_text = page.get_text("text").strip()
#         if page_text:
#             texts.append(f"--- PAGE {i+1} ---\n{page_text}")
#             continue

#         # Fallback to OCR
#         try:
#             pix = page.get_pixmap(dpi=300)
#             img_bytes = pix.tobytes("png")
#             if OCR_AVAILABLE:
#                 ocr_result = ocr_image_bytes(img_bytes, lang=ocr_lang).strip()
#                 texts.append(f"--- PAGE {i+1} (OCR) ---\n{ocr_result}")
#             else:
#                 texts.append(f"--- PAGE {i+1} ---\n[NO TEXT EXTRACTED; OCR NOT AVAILABLE]")
#         except Exception as e:
#             texts.append(f"--- PAGE {i+1} ---\n[ERROR RENDERING PAGE: {str(e)}]")

#     doc.close()
#     return "\n\n".join(texts)

# def image_bytes_to_text(img_bytes: bytes, ocr_lang: str = "eng") -> str:
#     """OCR for uploaded images (jpeg/png/webp)."""
#     if OCR_AVAILABLE:
#         return ocr_image_bytes(img_bytes, lang=ocr_lang)
#     return ""

# # ==================== TEXT CHUNKING ====================
# def chunk_text(text: str, max_chars: int = 20000) -> List[str]:
#     """Simple character-based chunking."""
#     if len(text) <= max_chars:
#         return [text]
#     chunks = []
#     start = 0
#     while start < len(text):
#         end = min(len(text), start + max_chars)
#         if end < len(text):
#             nl = text.rfind("\n", start, end)
#             if nl > start:
#                 end = nl + 1  # include newline
#         chunks.append(text[start:end])
#         start = end
#     return chunks

# # ==================== PDF GENERATOR (Flexible) ====================
# def generate_pdf(quote: dict) -> str:
#     pdf_path = os.path.join(TEMP_DIR, f"{quote['id']}.pdf")
#     doc = SimpleDocTemplate(pdf_path, pagesize=A4, topMargin=20*mm)
#     styles = getSampleStyleSheet()
#     styles.add(ParagraphStyle(name='TitleBig', fontSize=28, leading=32, alignment=1))
#     story = []

#     story.append(Paragraph("QUOTEFAST PRO", styles['TitleBig']))
#     story.append(Spacer(1, 20))
#     story.append(Paragraph(f"Date: {datetime.datetime.now().strftime('%d %B %Y')}", styles['Normal']))
#     story.append(Paragraph(f"Quote ID: {quote['id'][:8].upper()}", styles['Normal']))
#     story.append(Spacer(1, 30))

#     # Customer details
#     cust = quote.get('customer', {})
#     if cust:
#         story.append(Paragraph("<b>Customer Details</b>", styles['Heading2']))
#         for key, val in cust.items():
#             if val:
#                 story.append(Paragraph(f"{key.replace('_', ' ').title()}: {val}", styles['Normal']))
#         story.append(Spacer(1, 20))

#     # Savings summary
#     story.append(Paragraph("<b>Savings Summary</b>", styles['Heading2']))
#     data = [
#         ["", "Current", "Proposed", "You Save"],
#         ["Monthly (ex GST)", f"${quote['current_spend_ex']:.2f}", f"${quote['new_monthly_ex']:.2f}", f"${quote['monthly_saving_ex']:.2f}"],
#         ["Annual", "", "", f"${quote['monthly_saving_ex'] * 12:.2f}"]
#     ]
#     table = Table(data, colWidths=[200, 100, 100, 120])
#     table.setStyle(TableStyle([
#         ('BACKGROUND', (0,0), (-1,0), colors.grey),
#         ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
#         ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
#         ('BACKGROUND', (0,2), (-1,2), colors.lightgreen),
#     ]))
#     story.append(table)
#     story.append(Spacer(1, 30))

#     # Recommended line items
#     story.append(Paragraph("<b>Recommended Solution</b>", styles['Heading2']))
#     line_data = [["Qty", "Description", "Unit ex GST", "Total ex GST"]]
#     total = 0.0
#     for line in quote.get('selected_lines', []):
#         line_total = line['qty'] * line['unit_ex']
#         if line.get('cadence', 'monthly') == 'monthly':
#             total += line_total
#         line_data.append([str(line['qty']), line['desc'], f"${line['unit_ex']:.2f}", f"${line_total:.2f}"])
#     line_data.append(["", "", "Total Monthly", f"${total:.2f}"])

#     item_table = Table(line_data, colWidths=[50, 300, 100, 100])
#     item_table.setStyle(TableStyle([
#         ('GRID', (0,0), (-1,-1), 0.5, colors.black),
#         ('BACKGROUND', (0,0), (-1,0), colors.grey)
#     ]))
#     story.append(item_table)

#     story.append(Spacer(1, 40))
#     story.append(Paragraph("Valid 30 days. Contact rep for changes.", styles['Normal']))

#     doc.build(story)
#     return pdf_path

# # ==================== ENDPOINTS ====================
# @app.post("/analyze-bill", response_model=QuoteResponse)
# async def analyze_bill(
#     file: UploadFile = File(...),
#     max_pages: Optional[int] = Query(None, description="Limit how many pages to process (for very large PDFs)"),
#     ocr_lang: str = Query("eng", description="Tesseract OCR language (e.g. 'eng')"),
# ):
#     if file.content_type not in ["application/pdf", "image/jpeg", "image/png", "image/webp"]:
#         raise HTTPException(400, "Only PDF or images allowed")

#     contents = await file.read()

#     # Extract text
#     if file.content_type == "application/pdf":
#         full_text = pdf_extract_text(contents, max_pages=max_pages, ocr_lang=ocr_lang)
#     else:
#         full_text = image_bytes_to_text(contents, ocr_lang=ocr_lang)

#     if not full_text.strip():
#         raise HTTPException(500, "Failed to extract any text from the uploaded file. Ensure Tesseract is installed for scanned PDFs.")

#     # Chunk text
#     chunks = chunk_text(full_text, max_chars=18000)

#     # Build messages
#     messages = [{"role": "system", "content": GROK_PROMPT}]
#     for idx, chunk in enumerate(chunks):
#         messages.append({
#             "role": "user",
#             "content": f"Bill text chunk {idx+1}/{len(chunks)}:\n\n{chunk}"
#         })
#     messages.append({
#         "role": "user",
#         "content": "Now, using all chunks above, produce a single valid JSON object that contains the extracted customer details, current monthly spend (ex GST), and 1-3 recommended solutions as described in the system prompt. DO NOT output anything except valid JSON."
#     })

#     try:
#         response = client.chat.completions.create(
#             model="grok-4",
#             messages=messages,
#             response_format={"type": "json_object"},
#             max_tokens=3000
#         )
#         model_content = response.choices[0].message.content

#         raw_output = json.loads(model_content)

#         if not isinstance(raw_output, dict):
#             raise ValueError("Grok did not return a JSON object")

#     except Exception as e:
#         raise HTTPException(500, f"Grok failed: {str(e)}") from e

#     # Flexible parsing
#     customer = raw_output.get("customer", {})
#     current_spend = float(
#         raw_output.get("current_total_monthly_ex")
#         or raw_output.get("current_spend_ex")
#         or raw_output.get("current_monthly_spend_ex", 0)
#     )
#     recommendations = raw_output.get("recommendations", [])

#     if not recommendations:
#         raise HTTPException(500, "No recommendations in Grok output")

#     best_rec = recommendations[0]
#     lines_raw = best_rec.get("items") or best_rec.get("lines") or best_rec.get("line_items", [])
#     lines = [
#         QuoteLine(
#             sku=item.get("sku", "CUSTOM"),
#             desc=item.get("desc") or item.get("description", "Service"),
#             qty=int(item.get("qty") or item.get("quantity", 1)),
#             unit_ex=float(item.get("unit_ex") or item.get("price_ex") or item.get("unit_price_ex", 0)),
#             cadence=item.get("cadence", "monthly"),
#         )
#         for item in lines_raw
#     ]

#     new_monthly = float(
#         best_rec.get("new_monthly_ex")
#         or best_rec.get("proposed_spend")
#         or best_rec.get("proposed_monthly_ex", 0)
#     )
#     saving = current_spend - new_monthly

#     quote_id = str(uuid.uuid4())
#     quote = {
#         "id": quote_id,
#         "created": datetime.datetime.now().isoformat(),
#         "raw_grok_output": raw_output,
#         "customer": customer,
#         "current_spend_ex": current_spend,
#         "recommendations": recommendations,
#         "selected_lines": [line.dict() for line in lines],
#         "new_monthly_ex": new_monthly,
#         "monthly_saving_ex": saving,
#     }
#     quotes_db[quote_id] = quote

#     return QuoteResponse(**quote)

# @app.post("/select-recommendation/{quote_id}")
# async def select_recommendation(quote_id: str, index: int = Form(0)):
#     quote = quotes_db.get(quote_id)
#     if not quote or index >= len(quote["recommendations"]):
#         raise HTTPException(404)

#     rec = quote["recommendations"][index]
#     lines_raw = rec.get("items") or rec.get("lines") or rec.get("line_items", [])
#     lines = [
#         QuoteLine(
#             sku=item.get("sku", "CUSTOM"),
#             desc=item.get("desc") or item.get("description", "Service"),
#             qty=int(item.get("qty") or item.get("quantity", 1)),
#             unit_ex=float(item.get("unit_ex") or item.get("price_ex") or 0),
#             cadence=item.get("cadence", "monthly"),
#         ).dict()
#         for item in lines_raw
#     ]
#     quote["selected_lines"] = lines
#     quote["new_monthly_ex"] = float(rec.get("new_monthly_ex") or rec.get("proposed_spend") or 0)
#     quote["monthly_saving_ex"] = quote["current_spend_ex"] - quote["new_monthly_ex"]
#     return quote

# @app.post("/add-adhoc/{quote_id}")
# async def add_adhoc(
#     quote_id: str,
#     desc: str = Form(...),
#     qty: int = Form(1),
#     unit_ex: float = Form(...),
#     cadence: str = Form("once-off")
# ):
#     quote = quotes_db.get(quote_id)
#     if not quote:
#         raise HTTPException(404)
#     quote["selected_lines"].append(
#         QuoteLine(sku="ADHOC", desc=desc, qty=qty, unit_ex=unit_ex, cadence=cadence).dict()
#     )
#     return quote

# @app.get("/quote/{quote_id}")
# async def get_quote(quote_id: str):
#     quote = quotes_db.get(quote_id)
#     if not quote:
#         raise HTTPException(404)
#     return quote

# @app.get("/pdf/{quote_id}")
# async def get_pdf(quote_id: str):
#     quote = quotes_db.get(quote_id)
#     if not quote:
#         raise HTTPException(404)
#     return FileResponse(
#         generate_pdf(quote),
#         media_type="application/pdf",
#         filename=f"Quote_{quote_id[:8].upper()}.pdf"
#     )

# @app.get("/csv/{quote_id}")
# async def get_csv(quote_id: str):
#     quote = quotes_db.get(quote_id)
#     if not quote:
#         raise HTTPException(404)
#     path = os.path.join(TEMP_DIR, f"{quote_id}.csv")
#     with open(path, "w", newline="", encoding="utf-8") as f:
#         writer = csv.writer(f)
#         writer.writerow(["SKU", "Description", "Quantity", "Unit ex-GST", "GST", "Cadence", "HaaS term"])
#         for line in quote["selected_lines"]:
#             writer.writerow([
#                 line["sku"],
#                 line["desc"],
#                 line["qty"],
#                 line["unit_ex"],
#                 "10%",
#                 line["cadence"],
#                 line.get("haas_term", "")
#             ])
#     return FileResponse(path, media_type="text/csv", filename=f"Halo_{quote_id[:8].upper()}.csv")

# @app.get("/")
# async def root():
#     return {"message": "QUOTEFAST PRO – Flexible Grok Output Mode Active (OCR enabled)"}

# if __name__ == "__main__":
#     uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True)
import base64
import uuid
import datetime
import csv
import os
import tempfile
import io
import json
from typing import List, Dict, Optional
import fitz  # PyMuPDF
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn
# If using the official OpenAI library with an XAI base_url:
from openai import OpenAI
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm
from dotenv import load_dotenv
# OCR & image helpers
from PIL import Image
try:
    import pytesseract
    OCR_AVAILABLE = True
except Exception:  # pylint: disable=broad-except
    OCR_AVAILABLE = False

# ==================== SETUP ====================
load_dotenv()
XAI_API_KEY = os.getenv("XAI_API_KEY")
if not XAI_API_KEY:
    raise ValueError("Set XAI_API_KEY in .env")

# X.ai / XAI-compatible endpoint
client = OpenAI(base_url="https://api.x.ai/v1", api_key=XAI_API_KEY)

app = FastAPI(title="QUOTEFAST PRO v3.0 (OCR + Grok)")

quotes_db: Dict[str, dict] = {}  # In-memory for now; replace with PostgreSQL in production
TEMP_DIR = tempfile.gettempdir()

# ==================== FLEXIBLE PROMPT (No Static Structure) ====================
GROK_PROMPT = """You are an expert Australian telco bill analyst. Analyze the full uploaded bill (all pages). Extract all relevant customer details, current services, spend, and anything useful. Then, recommend 1-3 superior plans from our catalogue that beat the current bill (lower cost or better value). Use Gold bundles where possible (NBN $0 in bundle). Output ONLY valid JSON. Use whatever structure makes the most sense for this specific bill. Include at minimum: 
- customer info (type: Business or Residential, company (if Business), ABN/ACN (if Business), site_address, billing_address, main_contact_name, main_contact_number, main_contact_email, authorised_contact_name, authorised_contact_number, authorised_contact_email, secondary_contact_name, secondary_contact_number, secondary_contact_email, billing_contact_name, billing_contact_number, billing_contact_email, DIDs, etc.) 
- current monthly spend (ex GST) 
- recommendations with name, description, new monthly spend, saving, and line items (sku, desc, qty, unit_ex, cadence) 
Be creative with the structure if the bill has unusual sections — just make sure it's valid JSON that captures everything accurately.

Our catalogue (all prices ex GST unless stated; use these exactly for recommendations):
Mobile Plans (ex GST):
- 10Gb: $27
- 15Gb: $32
- 29Gb: $37
- 40Gb: $44
- 65Gb: $50
- 100Gb: $55
- 120Gb: $62
- 150Gb: $71
- 180Gb: $76

NBN Plans (ex GST):
- 12/1Mbps: $60.00
- 25/10Mbps: $60.00
- 50/20Mbps: $90.00
- FW Plus (100/20Mbps): $95.00
- 100/20Mbps: $95.00
- 500/50Mbps: $100.00
- FW Homefast 250/20: $100.00
- 100/40Mbps: $100.00
- FW Superfast 400/40: $110.00
- 750/50Mbps: $110.00
- 1000/100Mbps: $120.00
- 2000/100Mbps: $195.00
- 2000/200Mbps: $200.00

Build For Business Bundles (ex GST):
- 100/40Mbps (Bronze Bundled): $0.00
- 250/100Mbps (Bronze Bundled): $0.00
- 250/100Mbps (Gold Bundled): $120.00
- 500/200Mbps (Gold Bundled): $135.00
- 1000/400Mbps (Gold Bundled): $160.00
- 2000/500Mbps (Gold Bundled): $235.00

PBX Plans (ex GST):
- PAYG: $10
- Unlimited: $30

Call Rates for PAYG Customers (ex GST):
- Local/National Calls: Per Second Increments 0.050
- 13/1300: Per Call 0.46
- Mobile calls: Per Second Increments 0.17

DID Rates (ex GST):
- 1 Geo: 0.5
- 10 Geo: 5
- 100 Geo: 25

Hardware: ONCE OFF CHARGE (custom pricing based on needs; use ad-hoc if required)
"""

# ==================== MODELS (Minimal – Flexible) ====================
class QuoteLine(BaseModel):
    sku: Optional[str] = "CUSTOM"
    desc: str
    qty: int = 1
    unit_ex: float
    cadence: str = "monthly"
    haas_term: Optional[int] = None


class QuoteResponse(BaseModel):
    id: str
    created: str
    raw_grok_output: dict  # Whatever Grok gave us
    customer: dict
    current_spend_ex: float
    recommendations: list
    selected_lines: List[QuoteLine]
    new_monthly_ex: float
    monthly_saving_ex: float
    status: str = "Draft"  # Added for metadata


# ==================== OCR & TEXT EXTRACTION ====================
def ocr_image_bytes(img_bytes: bytes, lang: str = "eng") -> str:
    if not OCR_AVAILABLE:
        return ""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    try:
        return pytesseract.image_to_string(img, lang=lang)
    except Exception:  # fallback to basic config if lang not available
        return pytesseract.image_to_string(img)


def pdf_extract_text(pdf_bytes: bytes, max_pages: Optional[int] = None, ocr_lang: str = "eng") -> str:
    """Extract text from a PDF: native text first, fallback to OCR."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texts: List[str] = []
    page_count = len(doc)
    to_process = range(page_count) if max_pages is None else range(min(page_count, max_pages))
    for i in to_process:
        page = doc[i]
        page_text = page.get_text("text").strip()
        if page_text:
            texts.append(f"--- PAGE {i+1} ---\n{page_text}")
            continue
        # Fallback to OCR
        try:
            pix = page.get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            if OCR_AVAILABLE:
                ocr_result = ocr_image_bytes(img_bytes, lang=ocr_lang).strip()
                texts.append(f"--- PAGE {i+1} (OCR) ---\n{ocr_result}")
            else:
                texts.append(f"--- PAGE {i+1} ---\n[NO TEXT EXTRACTED; OCR NOT AVAILABLE]")
        except Exception as e:
            texts.append(f"--- PAGE {i+1} ---\n[ERROR RENDERING PAGE: {str(e)}]")
    doc.close()
    return "\n\n".join(texts)


def image_bytes_to_text(img_bytes: bytes, ocr_lang: str = "eng") -> str:
    """OCR for uploaded images (jpeg/png/webp)."""
    if OCR_AVAILABLE:
        return ocr_image_bytes(img_bytes, lang=ocr_lang)
    return ""


# ==================== TEXT CHUNKING ====================
def chunk_text(text: str, max_chars: int = 20000) -> List[str]:
    """Simple character-based chunking."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            nl = text.rfind("\n", start, end)
            if nl > start:
                end = nl + 1  # include newline
        chunks.append(text[start:end])
        start = end
    return chunks


# ==================== PDF GENERATOR (Flexible) ====================
def generate_pdf(quote: dict) -> str:
    pdf_path = os.path.join(TEMP_DIR, f"{quote['id']}.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=A4, topMargin=20 * mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleBig", fontSize=28, leading=32, alignment=1))
    story = []
    story.append(Paragraph("QUOTEFAST PRO", styles["TitleBig"]))
    story.append(Spacer(1, 20))
    story.append(Paragraph(f"Date: {datetime.datetime.now().strftime('%d %B %Y')}", styles["Normal"]))
    story.append(Paragraph(f"Quote ID: {quote['id'][:8].upper()}", styles["Normal"]))
    story.append(Spacer(1, 30))
    # Customer details
    cust = quote.get("customer", {})
    if cust:
        story.append(Paragraph("<b>Customer Details</b>", styles["Heading2"]))
        for key, val in cust.items():
            if val:
                story.append(Paragraph(f"{key.replace('_', ' ').title()}: {val}", styles["Normal"]))
        story.append(Spacer(1, 20))
    # Savings summary
    story.append(Paragraph("<b>Savings Summary</b>", styles["Heading2"]))
    data = [
        ["", "Current", "Proposed", "You Save"],
        ["Monthly (ex GST)", f"${quote['current_spend_ex']:.2f}", f"${quote['new_monthly_ex']:.2f}", f"${quote['monthly_saving_ex']:.2f}"],
        ["Annual", "", "", f"${quote['monthly_saving_ex'] * 12:.2f}"],
        ["24-mo saving", "", "", f"${quote['monthly_saving_ex'] * 24:.2f}"],  # Added 24-mo
    ]
    table = Table(data, colWidths=[200, 100, 100, 120])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("BACKGROUND", (0, 2), (-1, 2), colors.lightgreen),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 30))
    # Recommended line items (Monthly Recurring section)
    story.append(Paragraph("<b>Recommended Solution - Monthly Recurring</b>", styles["Heading2"]))
    line_data = [["Qty", "Description", "Unit ex GST", "Total ex GST"]]
    total_monthly = 0.0
    once_off_lines = []
    for line in quote.get("selected_lines", []):
        line_total = line["qty"] * line["unit_ex"]
        if line.get("cadence", "monthly") == "monthly":
            total_monthly += line_total
            line_data.append([str(line["qty"]), line["desc"], f"${line['unit_ex']:.2f}", f"${line_total:.2f}"])
        else:
            once_off_lines.append([str(line["qty"]), line["desc"], f"${line['unit_ex']:.2f}", f"${line_total:.2f}"])
    line_data.append(["", "", "Total Monthly", f"${total_monthly:.2f}"])
    item_table = Table(line_data, colWidths=[50, 300, 100, 100])
    item_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ]
        )
    )
    story.append(item_table)
    story.append(Spacer(1, 20))
    # Once-off charges section
    if once_off_lines:
        story.append(Paragraph("<b>Once-Off Charges</b>", styles["Heading2"]))
        once_off_data = [["Qty", "Description", "Unit ex GST", "Total ex GST"]] + once_off_lines
        once_off_table = Table(once_off_data, colWidths=[50, 300, 100, 100])
        once_off_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ]
            )
        )
        story.append(once_off_table)
        story.append(Spacer(1, 20))
    story.append(Paragraph("Valid 30 days. Contact rep for changes.", styles["Normal"]))
    story.append(Paragraph("Standard T&Cs apply. Attached separately.", styles["Normal"]))  # Added T&Cs mention
    doc.build(story)
    return pdf_path


# ==================== ENDPOINTS ====================
@app.post("/analyze-bill", response_model=QuoteResponse)
async def analyze_bill(
    file: UploadFile = File(...),
    customer_type: str = Form("Business", description="Business or Residential"),
    max_pages: Optional[int] = Query(None, description="Limit how many pages to process (for very large PDFs)"),
    ocr_lang: str = Query("eng", description="Tesseract OCR language (e.g. 'eng')"),
):
    if file.content_type not in ["application/pdf", "image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(400, "Only PDF or images allowed")
    contents = await file.read()
    # Extract text
    if file.content_type == "application/pdf":
        full_text = pdf_extract_text(contents, max_pages=max_pages, ocr_lang=ocr_lang)
    else:
        full_text = image_bytes_to_text(contents, ocr_lang=ocr_lang)
    if not full_text.strip():
        raise HTTPException(500, "Failed to extract any text from the uploaded file. Ensure Tesseract is installed for scanned PDFs.")
    # Chunk text
    chunks = chunk_text(full_text, max_chars=18000)
    # Build messages
    messages = [{"role": "system", "content": GROK_PROMPT}]
    messages.append({"role": "user", "content": f"Customer type: {customer_type}"})
    for idx, chunk in enumerate(chunks):
        messages.append(
            {
                "role": "user",
                "content": f"Bill text chunk {idx+1}/{len(chunks)}:\n\n{chunk}",
            }
        )
    messages.append(
        {
            "role": "user",
            "content": "Now, using all chunks above, produce a single valid JSON object that contains the extracted customer details, current monthly spend (ex GST), and 1-3 recommended solutions as described in the system prompt. DO NOT output anything except valid JSON.",
        }
    )
    try:
        response = client.chat.completions.create(
            model="grok-4",
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=3000,
        )
        model_content = response.choices[0].message.content
        raw_output = json.loads(model_content)
        if not isinstance(raw_output, dict):
            raise ValueError("Grok did not return a JSON object")
    except Exception as e:
        raise HTTPException(500, f"Grok failed: {str(e)}") from e
    # Flexible parsing
    customer = raw_output.get("customer", {})
    customer["type"] = customer_type  # Ensure type is set
    current_spend = float(
        raw_output.get("current_total_monthly_ex")
        or raw_output.get("current_spend_ex")
        or raw_output.get("current_monthly_spend_ex", 0)
    )
    recommendations = raw_output.get("recommendations", [])
    if not recommendations:
        raise HTTPException(500, "No recommendations in Grok output")
    best_rec = recommendations[0]
    lines_raw = best_rec.get("items") or best_rec.get("lines") or best_rec.get("line_items", [])
    lines = [
        QuoteLine(
            sku=item.get("sku", "CUSTOM"),
            desc=item.get("desc") or item.get("description", "Service"),
            qty=int(item.get("qty") or item.get("quantity", 1)),
            unit_ex=float(item.get("unit_ex") or item.get("price_ex") or item.get("unit_price_ex", 0)),
            cadence=item.get("cadence", "monthly"),
        )
        for item in lines_raw
    ]
    new_monthly = float(
        best_rec.get("new_monthly_ex")
        or best_rec.get("proposed_spend")
        or best_rec.get("proposed_monthly_ex", 0)
    )
    saving = current_spend - new_monthly
    quote_id = str(uuid.uuid4())
    quote = {
        "id": quote_id,
        "created": datetime.datetime.now().isoformat(),
        "raw_grok_output": raw_output,
        "customer": customer,
        "current_spend_ex": current_spend,
        "recommendations": recommendations,
        "selected_lines": [line.dict() for line in lines],
        "new_monthly_ex": new_monthly,
        "monthly_saving_ex": saving,
        "status": "Draft",  # Added
    }
    quotes_db[quote_id] = quote
    return QuoteResponse(**quote)


@app.post("/select-recommendation/{quote_id}")
async def select_recommendation(quote_id: str, index: int = Form(0)):
    quote = quotes_db.get(quote_id)
    if not quote or index >= len(quote["recommendations"]):
        raise HTTPException(404)
    rec = quote["recommendations"][index]
    lines_raw = rec.get("items") or rec.get("lines") or rec.get("line_items", [])
    lines = [
        QuoteLine(
            sku=item.get("sku", "CUSTOM"),
            desc=item.get("desc") or item.get("description", "Service"),
            qty=int(item.get("qty") or item.get("quantity", 1)),
            unit_ex=float(item.get("unit_ex") or item.get("price_ex") or 0),
            cadence=item.get("cadence", "monthly"),
        ).dict()
        for item in lines_raw
    ]
    quote["selected_lines"] = lines
    quote["new_monthly_ex"] = float(rec.get("new_monthly_ex") or rec.get("proposed_spend") or 0)
    quote["monthly_saving_ex"] = quote["current_spend_ex"] - quote["new_monthly_ex"]
    return quote


@app.post("/add-adhoc/{quote_id}")
async def add_adhoc(
    quote_id: str,
    desc: str = Form(...),
    qty: int = Form(1),
    unit_ex: float = Form(...),
    cadence: str = Form("once-off"),
):
    quote = quotes_db.get(quote_id)
    if not quote:
        raise HTTPException(404)
    quote["selected_lines"].append(
        QuoteLine(sku="ADHOC", desc=desc, qty=qty, unit_ex=unit_ex, cadence=cadence).dict()
    )
    return quote


@app.get("/quote/{quote_id}")
async def get_quote(quote_id: str):
    quote = quotes_db.get(quote_id)
    if not quote:
        raise HTTPException(404)
    return quote


@app.get("/quotes")
async def list_quotes():
    # For dashboard; in production, add auth and filters
    return list(quotes_db.values())


@app.post("/update-status/{quote_id}")
async def update_status(quote_id: str, status: str = Form(...)):
    quote = quotes_db.get(quote_id)
    if not quote:
        raise HTTPException(404)
    quote["status"] = status
    return quote


@app.get("/pdf/{quote_id}")
async def get_pdf(quote_id: str):
    quote = quotes_db.get(quote_id)
    if not quote:
        raise HTTPException(404)
    return FileResponse(
        generate_pdf(quote),
        media_type="application/pdf",
        filename=f"Quote_{quote_id[:8].upper()}.pdf",
    )


@app.get("/csv/{quote_id}")
async def get_csv(quote_id: str):
    quote = quotes_db.get(quote_id)
    if not quote:
        raise HTTPException(404)
    path = os.path.join(TEMP_DIR, f"{quote_id}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["SKU", "Description", "Quantity", "Unit ex-GST", "GST", "Cadence", "HaaS term"])
        for line in quote["selected_lines"]:
            writer.writerow(
                [
                    line["sku"],
                    line["desc"],
                    line["qty"],
                    line["unit_ex"],
                    "10%",
                    line["cadence"],
                    line.get("haas_term", ""),
                ]
            )
    return FileResponse(path, media_type="text/csv", filename=f"Halo_{quote_id[:8].upper()}.csv")


@app.get("/")
async def root():
    return {"message": "QUOTEFAST PRO – Flexible Grok Output Mode Active (OCR enabled)"}


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8001, reload=True)
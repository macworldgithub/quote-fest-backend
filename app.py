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
# from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Body
# from fastapi.responses import FileResponse
# from fastapi.middleware.cors import CORSMiddleware

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
# import motor.motor_asyncio
# import smtplib
# from email.mime.multipart import MIMEMultipart
# from email.mime.text import MIMEText
# from email.mime.application import MIMEApplication
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

# MONGO_URI = os.getenv("MONGO_URI")
# if not MONGO_URI:
#     raise ValueError("Set MONGO_URI in .env")

# SMTP_SERVER = os.getenv("SMTP_SERVER")
# SMTP_PORT = os.getenv("SMTP_PORT", 587)
# SMTP_USER = os.getenv("SMTP_USER")
# SMTP_PASS = os.getenv("SMTP_PASS")
# FROM_EMAIL = os.getenv("FROM_EMAIL")
# # Optional: if not set, send_email will raise
# if not all([SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASS, FROM_EMAIL]):
#     print("Warning: SMTP env vars not fully set; /send-email will fail.")

# TCS_PDF_PATH = os.getenv("TCS_PDF_PATH", "standard_tcs.pdf")

# # X.ai / XAI-compatible endpoint
# client = OpenAI(base_url="https://api.x.ai/v1", api_key=XAI_API_KEY)

# mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
# db = mongo_client["quotefast_db"]
# quotes_collection = db["quotes"]

# app = FastAPI(title="QUOTEFAST PRO v3.0 (OCR + Grok)")
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],          # Allow ALL origins
#     allow_credentials=True,
#     allow_methods=["*"],          # Allow all HTTP methods
#     allow_headers=["*"],          # Allow all headers
# )

# TEMP_DIR = tempfile.gettempdir()

# @app.on_event("startup")
# async def startup_event():
#     # Test MongoDB connection
#     await mongo_client.admin.command('ping')
#     print("MongoDB connected successfully")

# # ==================== FLEXIBLE PROMPT (No Static Structure) ====================
# GROK_PROMPT = """You are an expert Australian telco bill analyst. Analyze the full uploaded bill (all pages). Extract all relevant customer details, current services, spend, and anything useful. Then, recommend 1-3 superior plans from our catalogue that beat the current bill (lower cost or better value). Use Gold bundles where possible (NBN $0 in bundle). Output ONLY valid JSON. Use whatever structure makes the most sense for this specific bill. Include at minimum: 
# - customer info (type: Business or Residential, company (if Business), ABN/ACN (if Business), site_address, billing_address, main_contact_name, main_contact_number, main_contact_email, authorised_contact_name, authorised_contact_number, authorised_contact_email, secondary_contact_name, secondary_contact_number, secondary_contact_email, billing_contact_name, billing_contact_number, billing_contact_email, DIDs, etc.) 
# - current monthly spend (ex GST as well as inc GST if available) 
# - recommendations with name, description, new monthly spend, saving, and line items (sku, desc, qty, unit_ex, cadence) 
# Be creative with the structure if the bill has unusual sections — just make sure it's valid JSON that captures everything accurately.

# Our catalogue (all prices inc ; use these exactly for recommendations):
# Mobile Plans (inc GST):
# - 10Gb: $29.70
# - 15Gb: $35.20
# - 29Gb: $40.70
# - 40Gb: $48.40
# - 65Gb: $55.00
# - 100Gb: $60.50
# - 120Gb: $68.20
# - 150Gb: $78.10
# - 180Gb: $83.60

# NBN Plans (inc GST):
# - 12/1Mbps: $60.00
# - 25/10Mbps: $60.00
# - 50/20Mbps: $90.00
# - FW Plus (100/20Mbps): $95.00
# - 100/20Mbps: $95.00
# - 500/50Mbps: $100.00
# - FW Homefast 250/20: $100.00
# - 100/40Mbps: $100.00
# - FW Superfast 400/40: $110.00
# - 750/50Mbps: $110.00
# - 1000/100Mbps: $120.00
# - 2000/100Mbps: $195.00
# - 2000/200Mbps: $200.00

# Build For Business Bundles (inc GST):
# - 100/40Mbps (Bronze Bundled): $0.00
# - 250/100Mbps (Bronze Bundled): $0.00
# - 250/100Mbps (Gold Bundled): $120.00
# - 500/200Mbps (Gold Bundled): $135.00
# - 1000/400Mbps (Gold Bundled): $160.00
# - 2000/500Mbps (Gold Bundled): $235.00

# PBX Plans (inc GST):
# - PAYG: $10
# - Unlimited: $30

# Call Rates for PAYG Customers (inc GST):
# - Local/National Calls: Per Second Increments 0.050
# - 13/1300: Per Call 0.46
# - Mobile calls: Per Second Increments 0.17

# DID Rates (inc GST):
# - 1 Geo: 0.5
# - 10 Geo: 5
# - 100 Geo: 25

# Hardware: ONCE OFF CHARGE (custom pricing based on needs; use ad-hoc if required)

# Note: All catalogue prices are listed inc GST. For output in JSON, use ex GST values for unit_ex, current_spend_ex, new monthly spend, saving (calculate ex = inc / 1.1, round to 2 decimals). Output only ex GST figures.
# """

# EMAIL_PROMPT = """You are a sales email writer. For the given quote JSON, write a personalised professional email to the main contact, highlighting the savings and recommended solution. Include call to action to reply or call.

# Output JSON: {"subject": str, "body": str}"""

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
#     status: str = "Draft"  # Added for metadata


# class UpdateLine(BaseModel):
#     sku: Optional[str] = None
#     desc: Optional[str] = None
#     qty: Optional[int] = None
#     unit_ex: Optional[float] = None
#     cadence: Optional[str] = None
#     haas_term: Optional[int] = None


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
#     doc = SimpleDocTemplate(pdf_path, pagesize=A4, topMargin=20 * mm)
#     styles = getSampleStyleSheet()
#     styles.add(ParagraphStyle(name="TitleBig", fontSize=28, leading=32, alignment=1))
#     story = []
#     story.append(Paragraph("QUOTEFAST PRO", styles["TitleBig"]))
#     story.append(Spacer(1, 20))
#     story.append(Paragraph(f"Date: {datetime.datetime.now().strftime('%d %B %Y')}", styles["Normal"]))
#     story.append(Paragraph(f"Quote ID: {quote['id'][:8].upper()}", styles["Normal"]))
#     story.append(Spacer(1, 30))
#     # Customer details
#     cust = quote.get("customer", {})
#     if cust:
#         story.append(Paragraph("<b>Customer Details</b>", styles["Heading2"]))
#         for key, val in cust.items():
#             if val:
#                 story.append(Paragraph(f"{key.replace('_', ' ').title()}: {val}", styles["Normal"]))
#         story.append(Spacer(1, 20))
#     # Savings summary
#     story.append(Paragraph("<b>Savings Summary</b>", styles["Heading2"]))
#     data = [
#         ["", "Current", "Proposed", "You Save"],
#         ["Monthly (ex GST)", f"${quote['current_spend_ex']:.2f}", f"${quote['new_monthly_ex']:.2f}", f"${quote['monthly_saving_ex']:.2f}"],
#         ["Annual", "", "", f"${quote['monthly_saving_ex'] * 12:.2f}"],
#         ["24-mo saving", "", "", f"${quote['monthly_saving_ex'] * 24:.2f}"],  # Added 24-mo
#     ]
#     table = Table(data, colWidths=[200, 100, 100, 120])
#     table.setStyle(
#         TableStyle(
#             [
#                 ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
#                 ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
#                 ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
#                 ("BACKGROUND", (0, 2), (-1, 2), colors.lightgreen),
#             ]
#         )
#     )
#     story.append(table)
#     story.append(Spacer(1, 30))
#     # Recommended line items (Monthly Recurring section)
#     story.append(Paragraph("<b>Recommended Solution - Monthly Recurring</b>", styles["Heading2"]))
#     line_data = [["Qty", "Description", "Unit ex GST", "Total ex GST"]]
#     total_monthly = 0.0
#     once_off_lines = []
#     for line in quote.get("selected_lines", []):
#         line_total = line["qty"] * line["unit_ex"]
#         if line.get("cadence", "monthly") == "monthly":
#             total_monthly += line_total
#             line_data.append([str(line["qty"]), line["desc"], f"${line['unit_ex']:.2f}", f"${line_total:.2f}"])
#         else:
#             once_off_lines.append([str(line["qty"]), line["desc"], f"${line['unit_ex']:.2f}", f"${line_total:.2f}"])
#     line_data.append(["", "", "Total Monthly", f"${total_monthly:.2f}"])
#     item_table = Table(line_data, colWidths=[50, 300, 100, 100])
#     item_table.setStyle(
#         TableStyle(
#             [
#                 ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
#                 ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
#             ]
#         )
#     )
#     story.append(item_table)
#     story.append(Spacer(1, 20))
#     # Once-off charges section
#     if once_off_lines:
#         story.append(Paragraph("<b>Once-Off Charges</b>", styles["Heading2"]))
#         once_off_data = [["Qty", "Description", "Unit ex GST", "Total ex GST"]] + once_off_lines
#         once_off_table = Table(once_off_data, colWidths=[50, 300, 100, 100])
#         once_off_table.setStyle(
#             TableStyle(
#                 [
#                     ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
#                     ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
#                 ]
#             )
#         )
#         story.append(once_off_table)
#         story.append(Spacer(1, 20))
#     story.append(Paragraph("Valid 30 days. Contact rep for changes.", styles["Normal"]))
#     story.append(Paragraph("Standard T&Cs apply. Attached separately.", styles["Normal"]))  # Added T&Cs mention
#     doc.build(story)
#     return pdf_path


# # ==================== ENDPOINTS ====================
# @app.post("/analyze-bill", response_model=QuoteResponse)
# async def analyze_bill(
#     file: UploadFile = File(...),
#     customer_type: str = Form("Business", description="Business or Residential"),
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
#     messages.append({"role": "user", "content": f"Customer type: {customer_type}"})
#     for idx, chunk in enumerate(chunks):
#         messages.append(
#             {
#                 "role": "user",
#                 "content": f"Bill text chunk {idx+1}/{len(chunks)}:\n\n{chunk}",
#             }
#         )
#     messages.append(
#         {
#             "role": "user",
#             "content": "Now, using all chunks above, produce a single valid JSON object that contains the extracted customer details, current monthly spend (ex GST), and 1-3 recommended solutions as described in the system prompt. DO NOT output anything except valid JSON.",
#         }
#     )
#     try:
#         response = client.chat.completions.create(
#             model="grok-3-latest",
#             messages=messages,
#             response_format={"type": "json_object"},
#             max_tokens=3000,
#         )
#         model_content = response.choices[0].message.content
#         raw_output = json.loads(model_content)
#         if not isinstance(raw_output, dict):
#             raise ValueError("Grok did not return a JSON object")
#     except Exception as e:
#         raise HTTPException(500, f"Grok failed: {str(e)}") from e
#     # Flexible parsing
#     customer = raw_output.get("customer", {})
#     customer["type"] = customer_type  # Ensure type is set
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
#             haas_term=item.get("haas_term"),
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
#         "_id": quote_id,
#         "created": datetime.datetime.now().isoformat(),
#         "raw_grok_output": raw_output,
#         "customer": customer,
#         "current_spend_ex": current_spend,
#         "recommendations": recommendations,
#         "selected_lines": [line.dict() for line in lines],
#         "new_monthly_ex": new_monthly,
#         "monthly_saving_ex": saving,
#         "status": "Draft",  # Added
#     }
#     await quotes_collection.insert_one(quote)
#     # Verify insertion
#     inserted_quote = await quotes_collection.find_one({"_id": quote_id})
#     if not inserted_quote:
#         raise HTTPException(500, "Failed to insert quote into database")
#     return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})


# @app.post("/select-recommendation/{quote_id}")
# async def select_recommendation(quote_id: str, index: int = Form(0)):
#     quote = await quotes_collection.find_one({"_id": quote_id})
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
#             haas_term=item.get("haas_term"),
#         ).dict()
#         for item in lines_raw
#     ]
#     new_monthly = float(rec.get("new_monthly_ex") or rec.get("proposed_spend") or 0)
#     saving = quote["current_spend_ex"] - new_monthly
#     updates = {
#         "selected_lines": lines,
#         "new_monthly_ex": new_monthly,
#         "monthly_saving_ex": saving
#     }
#     await quotes_collection.update_one({"_id": quote_id}, {"$set": updates})
#     quote.update(updates)
#     return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})


# @app.post("/add-adhoc/{quote_id}")
# async def add_adhoc(
#     quote_id: str,
#     desc: str = Form(...),
#     qty: int = Form(1),
#     unit_ex: float = Form(...),
#     cadence: str = Form("once-off"),
#     haas_term: Optional[int] = Form(None),
# ):
#     new_line = QuoteLine(sku="ADHOC", desc=desc, qty=qty, unit_ex=unit_ex, cadence=cadence, haas_term=haas_term).dict()
#     result = await quotes_collection.update_one({"_id": quote_id}, {"$push": {"selected_lines": new_line}})
#     if result.modified_count == 0:
#         raise HTTPException(404)
#     quote = await quotes_collection.find_one({"_id": quote_id})
#     new_monthly = sum(l["qty"] * l["unit_ex"] for l in quote["selected_lines"] if l["cadence"] == "monthly")
#     saving = quote["current_spend_ex"] - new_monthly
#     await quotes_collection.update_one({"_id": quote_id}, {"$set": {"new_monthly_ex": new_monthly, "monthly_saving_ex": saving}})
#     return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})


# @app.post("/update-line/{quote_id}")
# async def update_line(quote_id: str, index: int, update: UpdateLine = Body(...)):
#     quote = await quotes_collection.find_one({"_id": quote_id})
#     if not quote or index >= len(quote["selected_lines"]):
#         raise HTTPException(404)
#     line = quote["selected_lines"][index]
#     for k, v in update.dict(exclude_unset=True).items():
#         line[k] = v
#     new_monthly = sum(l["qty"] * l["unit_ex"] for l in quote["selected_lines"] if l["cadence"] == "monthly")
#     saving = quote["current_spend_ex"] - new_monthly
#     await quotes_collection.update_one({"_id": quote_id}, {"$set": {"selected_lines": quote["selected_lines"], "new_monthly_ex": new_monthly, "monthly_saving_ex": saving}})
#     return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})


# @app.post("/remove-line/{quote_id}")
# async def remove_line(quote_id: str, index: int = Form(...)):
#     quote = await quotes_collection.find_one({"_id": quote_id})
#     if not quote or index >= len(quote["selected_lines"]):
#         raise HTTPException(404)
#     del quote["selected_lines"][index]
#     new_monthly = sum(l["qty"] * l["unit_ex"] for l in quote["selected_lines"] if l["cadence"] == "monthly")
#     saving = quote["current_spend_ex"] - new_monthly
#     await quotes_collection.update_one({"_id": quote_id}, {"$set": {"selected_lines": quote["selected_lines"], "new_monthly_ex": new_monthly, "monthly_saving_ex": saving}})
#     return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})


# @app.get("/quote/{quote_id}")
# async def get_quote(quote_id: str):
#     quote = await quotes_collection.find_one({"_id": quote_id})
#     if not quote:
#         raise HTTPException(404)
#     return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})


# @app.get("/quotes")
# async def list_quotes():
#     # For dashboard; in production, add auth and filters
#     quotes = await quotes_collection.find().to_list(None)
#     return [QuoteResponse(id=q["_id"], **{k: q[k] for k in q if k != "_id"}) for q in quotes]


# @app.post("/update-status/{quote_id}")
# async def update_status(quote_id: str, status: str = Form(...)):
#     result = await quotes_collection.update_one({"_id": quote_id}, {"$set": {"status": status}})
#     if result.modified_count == 0:
#         raise HTTPException(404)
#     quote = await quotes_collection.find_one({"_id": quote_id})
#     return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})


# @app.get("/pdf/{quote_id}")
# async def get_pdf(quote_id: str):
#     quote = await quotes_collection.find_one({"_id": quote_id})
#     if not quote:
#         raise HTTPException(404)
#     quote["id"] = quote_id  # For PDF gen
#     return FileResponse(
#         generate_pdf(quote),
#         media_type="application/pdf",
#         filename=f"Quote_{quote_id[:8].upper()}.pdf",
#     )


# @app.get("/csv/{quote_id}")
# async def get_csv(quote_id: str):
#     quote = await quotes_collection.find_one({"_id": quote_id})
#     if not quote:
#         raise HTTPException(404)
#     path = os.path.join(TEMP_DIR, f"{quote_id}.csv")
#     with open(path, "w", newline="", encoding="utf-8") as f:
#         writer = csv.writer(f)
#         writer.writerow(["SKU", "Description", "Quantity", "Unit ex-GST", "GST", "Cadence", "HaaS term"])
#         for line in quote["selected_lines"]:
#             writer.writerow(
#                 [
#                     line["sku"],
#                     line["desc"],
#                     line["qty"],
#                     line["unit_ex"],
#                     "10%",
#                     line["cadence"],
#                     line.get("haas_term", ""),
#                 ]
#             )
#     return FileResponse(path, media_type="text/csv", filename=f"Halo_{quote_id[:8].upper()}.csv")


# @app.post("/send-email/{quote_id}")
# async def send_email(quote_id: str, to_email: str = Form(...)):
#     quote = await quotes_collection.find_one({"_id": quote_id})
#     if not quote:
#         raise HTTPException(404)
#     quote["id"] = quote_id  # For PDF
#     # Generate email content with Grok
#     messages = [{"role": "system", "content": EMAIL_PROMPT}]
#     messages.append({"role": "user", "content": json.dumps(quote)})
#     try:
#         response = client.chat.completions.create(
#             model="grok-3-latest",
#             messages=messages,
#             response_format={"type": "json_object"},
#             max_tokens=1000,
#         )
#         email_content = json.loads(response.choices[0].message.content)
#         subject = email_content["subject"]
#         body = email_content["body"]
#     except Exception as e:
#         raise HTTPException(500, f"Grok email generation failed: {str(e)}") from e
#     pdf_path = generate_pdf(quote)
#     msg = MIMEMultipart()
#     msg["From"] = FROM_EMAIL
#     msg["To"] = to_email
#     msg["Subject"] = subject
#     msg.attach(MIMEText(body, "plain"))
#     with open(pdf_path, "rb") as f:
#         attach = MIMEApplication(f.read(), _subtype="pdf")
#         attach.add_header("Content-Disposition", "attachment", filename=f"Quote_{quote_id[:8].upper()}.pdf")
#         msg.attach(attach)
#     if os.path.exists(TCS_PDF_PATH):
#         with open(TCS_PDF_PATH, "rb") as f:
#             attach = MIMEApplication(f.read(), _subtype="pdf")
#             attach.add_header("Content-Disposition", "attachment", filename="Standard_TCs.pdf")
#             msg.attach(attach)
#     try:
#         with smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT)) as server:
#             server.starttls()
#             server.login(SMTP_USER, SMTP_PASS)
#             server.send_message(msg)
#     except Exception as e:
#         raise HTTPException(500, f"Email sending failed: {str(e)}") from e
#     await quotes_collection.update_one({"_id": quote_id}, {"$set": {"status": "Sent"}})
#     return {"message": "Email sent successfully"}


# @app.get("/")
# async def root():
#     return {"message": "QUOTEFAST PRO – Flexible Grok Output Mode Active (OCR enabled)"}


# if __name__ == "__main__":
#     uvicorn.run("app:app", host="0.0.0.0", port=7002, reload=True)
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
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Body
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel
import uvicorn
from openai import OpenAI
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER
from dotenv import load_dotenv
import motor.motor_asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from PIL import Image

try:
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# ==================== SETUP ====================
load_dotenv()
XAI_API_KEY = os.getenv("XAI_API_KEY")
if not XAI_API_KEY:
    raise ValueError("Set XAI_API_KEY in .env")

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise ValueError("Set MONGO_URI in .env")

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = os.getenv("SMTP_PORT", 587)
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL")
if not all([SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASS, FROM_EMAIL]):
    print("Warning: SMTP env vars not fully set; /send-email will fail.")

TCS_PDF_PATH = os.getenv("TCS_PDF_PATH", "standard_tcs.pdf")

client = OpenAI(base_url="https://api.x.ai/v1", api_key=XAI_API_KEY)

mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = mongo_client["quotefast_db"]
quotes_collection = db["quotes"]

app = FastAPI(title="QUOTEFAST PRO v3.0 (OCR + Grok)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP_DIR = tempfile.gettempdir()

@app.on_event("startup")
async def startup_event():
    await mongo_client.admin.command('ping')
    print("MongoDB connected successfully")

# ==================== PROMPTS ====================
GROK_PROMPT = """You are an expert Australian telco bill analyst. Analyze the full uploaded bill (all pages). Extract all relevant customer details, current services, spend, and anything useful. Then, recommend 1-3 superior plans from our catalogue that beat the current bill (lower cost or better value). Use Gold bundles where possible (NBN $0 in bundle). Output ONLY valid JSON. Use whatever structure makes the most sense for this specific bill. Include at minimum: 
- customer info (type: Business or Residential, company (if Business), ABN/ACN (if Business), site_address, billing_address, main_contact_name, main_contact_number, main_contact_email, authorised_contact_name, authorised_contact_number, authorised_contact_email, secondary_contact_name, secondary_contact_number, secondary_contact_email, billing_contact_name, billing_contact_number, billing_contact_email, DIDs, etc.) 
- current monthly spend (ex GST as well as inc GST if available) 
- recommendations with name, description, new monthly spend, saving, and line items (sku, desc, qty, unit_ex, cadence) 
Be creative with the structure if the bill has unusual sections — just make sure it's valid JSON that captures everything accurately.

Our catalogue (all prices inc ; use these exactly for recommendations):
Mobile Plans (inc GST):
- 10Gb: $29.70
- 15Gb: $35.20
- 29Gb: $40.70
- 40Gb: $48.40
- 65Gb: $55.00
- 100Gb: $60.50
- 120Gb: $68.20
- 150Gb: $78.10
- 180Gb: $83.60

NBN Plans (inc GST):
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

Build For Business Bundles (inc GST):
- 100/40Mbps (Bronze Bundled): $0.00
- 250/100Mbps (Bronze Bundled): $0.00
- 250/100Mbps (Gold Bundled): $120.00
- 500/200Mbps (Gold Bundled): $135.00
- 1000/400Mbps (Gold Bundled): $160.00
- 2000/500Mbps (Gold Bundled): $235.00

PBX Plans (inc GST):
- PAYG: $10
- Unlimited: $30

Call Rates for PAYG Customers (inc GST):
- Local/National Calls: Per Second Increments 0.050
- 13/1300: Per Call 0.46
- Mobile calls: Per Second Increments 0.17

DID Rates (inc GST):
- 1 Geo: 0.5
- 10 Geo: 5
- 100 Geo: 25

Hardware: ONCE OFF CHARGE (custom pricing based on needs; use ad-hoc if required)

Note: All catalogue prices are listed inc GST. For output in JSON, use ex GST values for unit_ex, current_spend_ex, new monthly spend, saving (calculate ex = inc / 1.1, round to 2 decimals). Output only ex GST figures.
"""

EMAIL_PROMPT = """You are a sales email writer. For the given quote JSON, write a personalised professional email to the main contact, highlighting the savings and recommended solution. Include call to action to reply or call.

Output JSON: {"subject": str, "body": str}"""

# ==================== MODELS ====================
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
    raw_grok_output: dict
    customer: dict
    current_spend_ex: float
    recommendations: list
    selected_lines: List[QuoteLine]
    new_monthly_ex: float
    monthly_saving_ex: float
    status: str = "Draft"

class UpdateLine(BaseModel):
    sku: Optional[str] = None
    desc: Optional[str] = None
    qty: Optional[int] = None
    unit_ex: Optional[float] = None
    cadence: Optional[str] = None
    haas_term: Optional[int] = None

# ==================== OCR & TEXT EXTRACTION ====================
def ocr_image_bytes(img_bytes: bytes, lang: str = "eng") -> str:
    if not OCR_AVAILABLE:
        return ""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    try:
        return pytesseract.image_to_string(img, lang=lang)
    except Exception:
        return pytesseract.image_to_string(img)

def pdf_extract_text(pdf_bytes: bytes, max_pages: Optional[int] = None, ocr_lang: str = "eng") -> str:
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
    if OCR_AVAILABLE:
        return ocr_image_bytes(img_bytes, lang=ocr_lang)
    return ""

def chunk_text(text: str, max_chars: int = 18000) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            nl = text.rfind("\n", start, end)
            if nl > start:
                end = nl + 1
        chunks.append(text[start:end])
        start = end
    return chunks

# ==================== PDF GENERATOR - Matches React Preview Exactly ====================
def generate_pdf(quote: dict) -> str:
    pdf_path = os.path.join(TEMP_DIR, f"{quote['id']}.pdf")
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=20 * mm
    )
    styles = getSampleStyleSheet()

    # Custom styles
    styles.add(ParagraphStyle(name="TitleBig", fontSize=28, leading=34, alignment=TA_CENTER, spaceAfter=12, textColor=colors.HexColor("#111111")))
    styles.add(ParagraphStyle(name="Subtitle", fontSize=13, textColor=colors.HexColor("#666666"), alignment=TA_CENTER, spaceAfter=30))
    styles.add(ParagraphStyle(name="SectionHeader", fontSize=16, fontName="Helvetica-Bold", spaceBefore=25, spaceAfter=12, textColor=colors.HexColor("#111111")))

    story = []

    # Header
    story.append(Paragraph("Telco Quote", styles["TitleBig"]))
    customer_type = quote.get("customer", {}).get("type", "Business")
    story.append(Paragraph("Business Solution" if customer_type == "Business" else "Residential Solution", styles["Subtitle"]))
    story.append(Spacer(1, 10))

    # Customer Details
    story.append(Paragraph("Customer Details", styles["SectionHeader"]))
    customer = quote.get("customer", {})

    def get_val(keys):
        if not isinstance(keys, list):
            keys = [keys]
        for key in keys:
            val = customer.get(key)
            if not val or str(val).strip().lower() in ["not provided", "n/a", "null", ""]:
                continue
            if isinstance(val, dict):
                parts = [val.get(k) for k in ["street", "line1", "suburb", "city", "state", "postcode", "zip"] if val.get(k)]
                if parts:
                    return ", ".join(parts)
                return str(val)
            return str(val).strip()
        return "N/A"

    cust_rows = []
    for label, key_list in [
        ("Company", ["company", "company_name"]),
        ("ABN", ["abn", "acn"]),
        ("Site Address", ["site_address", "address"]),
        ("Billing Address", ["billing_address"]),
        ("Contact", ["main_contact_name", "contact_name", "billing_contact_name"]),
        ("Email", ["main_contact_email", "email", "billing_contact_email"]),
        ("Phone", ["main_contact_number", "main_contact_phone", "phone", "billing_contact_number"]),
    ]:
        val = get_val(key_list)
        if val != "N/A":
            cust_rows.append([label, val])

    if cust_rows:
        cust_table = Table(cust_rows, colWidths=[120, 360])
        cust_table.setStyle(TableStyle([
            ('FONTSIZE', (0,0), (-1,-1), 10),
            ('LEFTPADDING', (0,0), (0,-1), 0),
            ('LEFTPADDING', (1,0), (1,-1), 10),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor("#666666")),
            ('TEXTCOLOR', (1,0), (1,-1), colors.HexColor("#111111")),
            ('FONTNAME', (1,0), (1,-1), 'Helvetica-Bold'),
        ]))
        story.append(cust_table)
    else:
        story.append(Paragraph("No customer details available", styles["Normal"]))

    story.append(Spacer(1, 25))

    # Quote Lines
    story.append(Paragraph("Quote Lines", styles["SectionHeader"]))
    line_items = quote.get("selected_lines", [])
    line_data = [["Description", "Qty", "Unit (ex-GST)", "Total"]]
    once_off_lines = []

    for line in line_items:
        qty = line.get("qty", 1)
        unit_ex = line.get("unit_ex", 0.0)
        total = qty * unit_ex
        desc = line.get("desc", "Service")
        row = [desc, str(qty), f"${unit_ex:.2f}", f"${total:.2f}"]
        if line.get("cadence", "monthly").lower() == "monthly":
            line_data.append(row)
        else:
            once_off_lines.append(row)

    line_table = Table(line_data, colWidths=[280, 60, 80, 80])
    line_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f3f4f6")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor("#666666")),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e5e7eb")),
        ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,1), (0,-1), 8),
        ('RIGHTPADDING', (0,1), (-1,-1), 8),
    ]))
    story.append(line_table)

    if once_off_lines:
        story.append(Spacer(1, 15))
        story.append(Paragraph("Once-Off Charges", styles["SectionHeader"]))
        once_off_data = [["Description", "Qty", "Unit (ex-GST)", "Total"]] + once_off_lines
        once_table = Table(once_off_data, colWidths=[280, 60, 80, 80])
        once_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f3f4f6")),
            ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor("#666666")),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 10),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e5e7eb")),
            ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,1), (0,-1), 8),
            ('RIGHTPADDING', (0,1), (-1,-1), 8),
        ]))
        story.append(once_table)

    story.append(Spacer(1, 30))

    # Savings Summary Box
    current = quote.get("current_spend_ex", 0.0)
    proposed = quote.get("new_monthly_ex", 0.0)
    saving = quote.get("monthly_saving_ex", 0.0)

    savings_data = [
        ["Current monthly spend:", f"${current:.2f}"],
        ["New monthly recurring:", f"${proposed:.2f}"],
        ["", ""],
        ["Monthly saving:", f"${saving:.2f}"],
        ["24-month saving:", f"${saving * 24:.2f}"],
    ]

    savings_table = Table(savings_data, colWidths=[320, 160])
    savings_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f0fdf4")),
        ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor("#86efac")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#bbf7d0")),
        ('FONTSIZE', (0,0), (-1,-1), 12),
        ('LEFTPADDING', (0,0), (-1,-1), 20),
        ('RIGHTPADDING', (0,0), (-1,-1), 20),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('FONTNAME', (0,3), (0,4), 'Helvetica-Bold'),
        ('FONTNAME', (1,3), (1,4), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0,3), (1,4), colors.HexColor("#166534")),
        ('FONTSIZE', (1,3), (1,4), 13),
        ('LINEABOVE', (0,3), (-1,3), 1, colors.HexColor("#86efac")),
        ('SPAN', (0,2), (-1,2)),
    ]))
    story.append(savings_table)

    story.append(Spacer(1, 40))
    story.append(Paragraph("Valid for 30 days from issue date", styles["Normal"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Terms & Conditions apply • NBN availability subject to NBNCO assessment", styles["Normal"]))

    doc.build(story)
    return pdf_path

# ==================== ENDPOINTS ====================
@app.post("/analyze-bill", response_model=QuoteResponse)
async def analyze_bill(
    file: UploadFile = File(...),
    customer_type: str = Form("Business"),
    max_pages: Optional[int] = Query(None),
    ocr_lang: str = Query("eng"),
):
    if file.content_type not in ["application/pdf", "image/jpeg", "image/png", "image/webp"]:
        raise HTTPException(400, "Only PDF or images allowed")
    contents = await file.read()

    if file.content_type == "application/pdf":
        full_text = pdf_extract_text(contents, max_pages=max_pages, ocr_lang=ocr_lang)
    else:
        full_text = image_bytes_to_text(contents, ocr_lang=ocr_lang)

    if not full_text.strip():
        raise HTTPException(500, "Failed to extract any text from the uploaded file.")

    chunks = chunk_text(full_text, max_chars=18000)
    messages = [{"role": "system", "content": GROK_PROMPT}]
    messages.append({"role": "user", "content": f"Customer type: {customer_type}"})
    for idx, chunk in enumerate(chunks):
        messages.append({"role": "user", "content": f"Bill text chunk {idx+1}/{len(chunks)}:\n\n{chunk}"})
    messages.append({"role": "user", "content": "Now, using all chunks above, produce a single valid JSON object."})

    try:
        response = client.chat.completions.create(
            model="grok-3-latest",
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

    # === FLEXIBLE CUSTOMER & SPEND PARSING ===
    possible_customer_keys = ["customer", "customer_info", "customer_details", "client", "account", "customer_data", "billing_info"]
    customer = {}
    for key in possible_customer_keys:
        if key in raw_output and isinstance(raw_output[key], dict):
            customer = raw_output[key].copy()
            break
    customer["type"] = customer_type

    # Current spend
    current_spend_ex = 0.0
    direct_keys = ["current_total_monthly_ex", "current_spend_ex", "current_monthly_spend_ex", "current_monthly_ex", "current_ex_gst", "monthly_ex_gst"]
    for key in direct_keys:
        if key in raw_output:
            try:
                current_spend_ex = float(raw_output[key])
                break
            except (TypeError, ValueError):
                continue

    if current_spend_ex == 0.0:
        spend_obj = raw_output.get("current_spend") or raw_output.get("current_spend_details") or raw_output.get("current_cost") or {}
        nested_keys = ["monthly_ex_gst", "ex_gst", "monthly_ex", "total_ex_gst", "amount_ex"]
        for key in nested_keys:
            if key in spend_obj:
                try:
                    current_spend_ex = float(spend_obj[key])
                    break
                except (TypeError, ValueError):
                    continue

    # Recommendations
    recommendations = raw_output.get("recommendations", [])
    if not recommendations:
        raise HTTPException(500, "No recommendations in Grok output")

    best_rec = recommendations[0]
    lines_raw = best_rec.get("items") or best_rec.get("lines") or best_rec.get("line_items") or best_rec.get("services") or []

    lines = []
    for item in lines_raw:
        try:
            lines.append(QuoteLine(
                sku=item.get("sku", "CUSTOM"),
                desc=item.get("desc") or item.get("description") or "Service",
                qty=int(item.get("qty") or item.get("quantity") or 1),
                unit_ex=float(item.get("unit_ex") or item.get("price_ex") or item.get("unit_price_ex") or 0),
                cadence=item.get("cadence", "monthly").lower(),
                haas_term=item.get("haas_term"),
            ))
        except (TypeError, ValueError):
            continue

    new_monthly_ex = 0.0
    new_keys = ["new_monthly_ex", "proposed_spend", "new_monthly_spend_ex_gst", "proposed_monthly_ex"]
    for key in new_keys:
        if key in best_rec:
            try:
                new_monthly_ex = float(best_rec[key])
                break
            except (TypeError, ValueError):
                continue

    if new_monthly_ex == 0.0:
        new_monthly_ex = sum(l.qty * l.unit_ex for l in lines if l.cadence == "monthly")

    monthly_saving_ex = current_spend_ex - new_monthly_ex

    quote_id = str(uuid.uuid4())
    quote = {
        "_id": quote_id,
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "raw_grok_output": raw_output,
        "customer": customer,
        "current_spend_ex": round(current_spend_ex, 2),
        "recommendations": recommendations,
        "selected_lines": [line.dict() for line in lines],
        "new_monthly_ex": round(new_monthly_ex, 2),
        "monthly_saving_ex": round(monthly_saving_ex, 2),
        "status": "Draft",
    }

    await quotes_collection.insert_one(quote)

    inserted_quote = await quotes_collection.find_one({"_id": quote_id})
    if not inserted_quote:
        raise HTTPException(500, "Failed to insert quote into database")

    return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})

# Keep all your other endpoints exactly as they were (select-recommendation, add-adhoc, etc.)
# They are unchanged and work perfectly with this fix.
@app.post("/select-recommendation/{quote_id}")
async def select_recommendation(quote_id: str, index: int = Form(0)):
    quote = await quotes_collection.find_one({"_id": quote_id})
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
            haas_term=item.get("haas_term"),
        ).dict()
        for item in lines_raw
    ]
    new_monthly = float(rec.get("new_monthly_ex") or rec.get("proposed_spend") or 0)
    saving = quote["current_spend_ex"] - new_monthly
    updates = {
        "selected_lines": lines,
        "new_monthly_ex": new_monthly,
        "monthly_saving_ex": saving
    }
    await quotes_collection.update_one({"_id": quote_id}, {"$set": updates})
    quote.update(updates)
    return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})


@app.post("/add-adhoc/{quote_id}")
async def add_adhoc(
    quote_id: str,
    desc: str = Form(...),
    qty: int = Form(1),
    unit_ex: float = Form(...),
    cadence: str = Form("once-off"),
    haas_term: Optional[int] = Form(None),
):
    new_line = QuoteLine(sku="ADHOC", desc=desc, qty=qty, unit_ex=unit_ex, cadence=cadence, haas_term=haas_term).dict()
    result = await quotes_collection.update_one({"_id": quote_id}, {"$push": {"selected_lines": new_line}})
    if result.modified_count == 0:
        raise HTTPException(404)
    quote = await quotes_collection.find_one({"_id": quote_id})
    new_monthly = sum(l["qty"] * l["unit_ex"] for l in quote["selected_lines"] if l["cadence"] == "monthly")
    saving = quote["current_spend_ex"] - new_monthly
    await quotes_collection.update_one({"_id": quote_id}, {"$set": {"new_monthly_ex": new_monthly, "monthly_saving_ex": saving}})
    return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})


@app.post("/update-line/{quote_id}")
async def update_line(quote_id: str, index: int, update: UpdateLine = Body(...)):
    quote = await quotes_collection.find_one({"_id": quote_id})
    if not quote or index >= len(quote["selected_lines"]):
        raise HTTPException(404)
    line = quote["selected_lines"][index]
    for k, v in update.dict(exclude_unset=True).items():
        line[k] = v
    new_monthly = sum(l["qty"] * l["unit_ex"] for l in quote["selected_lines"] if l["cadence"] == "monthly")
    saving = quote["current_spend_ex"] - new_monthly
    await quotes_collection.update_one({"_id": quote_id}, {"$set": {"selected_lines": quote["selected_lines"], "new_monthly_ex": new_monthly, "monthly_saving_ex": saving}})
    return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})


@app.post("/remove-line/{quote_id}")
async def remove_line(quote_id: str, index: int = Form(...)):
    quote = await quotes_collection.find_one({"_id": quote_id})
    if not quote or index >= len(quote["selected_lines"]):
        raise HTTPException(404)
    del quote["selected_lines"][index]
    new_monthly = sum(l["qty"] * l["unit_ex"] for l in quote["selected_lines"] if l["cadence"] == "monthly")
    saving = quote["current_spend_ex"] - new_monthly
    await quotes_collection.update_one({"_id": quote_id}, {"$set": {"selected_lines": quote["selected_lines"], "new_monthly_ex": new_monthly, "monthly_saving_ex": saving}})
    return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})


@app.get("/quote/{quote_id}")
async def get_quote(quote_id: str):
    quote = await quotes_collection.find_one({"_id": quote_id})
    if not quote:
        raise HTTPException(404)
    return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})
@app.post("/update-customer/{quote_id}")
async def update_customer(quote_id: str, customer_data: dict = Body(...)):
    """
    Update the customer object in the quote.
    customer_data should contain the updated fields (e.g. company, site_address, main_contact_email, etc.)
    """
    result = await quotes_collection.update_one(
        {"_id": quote_id},
        {"$set": {"customer": customer_data}}
    )
    
    if result.modified_count == 0:
        # Could be not found or no changes
        quote = await quotes_collection.find_one({"_id": quote_id})
        if not quote:
            raise HTTPException(status_code=404, detail="Quote not found")
    
    updated_quote = await quotes_collection.find_one({"_id": quote_id})
    return QuoteResponse(
        id=quote_id,
        **{k: updated_quote[k] for k in updated_quote if k != "_id"}
    )

@app.get("/quotes")
async def list_quotes():
    # For dashboard; in production, add auth and filters
    quotes = await quotes_collection.find().to_list(None)
    return [QuoteResponse(id=q["_id"], **{k: q[k] for k in q if k != "_id"}) for q in quotes]


@app.post("/update-status/{quote_id}")
async def update_status(quote_id: str, status: str = Form(...)):
    print(quote_id, status)
    result = await quotes_collection.update_one({"_id": quote_id}, {"$set": {"status": status}})
    print(result)
    if result.modified_count == 0:
        raise HTTPException(404)
    quote = await quotes_collection.find_one({"_id": quote_id})
    return QuoteResponse(id=quote_id, **{k: quote[k] for k in quote if k != "_id"})

@app.get("/pdf/{quote_id}")
async def get_pdf(quote_id: str):
    quote = await quotes_collection.find_one({"_id": quote_id})
    if not quote:
        raise HTTPException(404)
    quote["id"] = quote_id
    return FileResponse(
        generate_pdf(quote),
        media_type="application/pdf",
        filename=f"Quote_{quote_id[:8].upper()}.pdf",
    )


@app.get("/csv/{quote_id}")
async def get_csv(quote_id: str):
    quote = await quotes_collection.find_one({"_id": quote_id})
    if not quote:
        raise HTTPException(404)

    path = os.path.join(TEMP_DIR, f"{quote_id}.csv")
    
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # === HEADER SECTION ===
        writer.writerow(["QUOTEFAST PRO - FULL QUOTE EXPORT"])
        writer.writerow(["Quote ID", quote_id[:8].upper()])
        writer.writerow(["Generated on", datetime.datetime.now().strftime("%d %B %Y")])
        writer.writerow([])

        # === CUSTOMER DETAILS ===
        writer.writerow(["CUSTOMER DETAILS"])
        customer = quote.get("customer", {})

        # Helper function to format address dict → clean multi-line string (using | as separator in CSV)
        def format_address(addr):
            if not addr:
                return "N/A"
            if isinstance(addr, str):
                return addr.strip() or "N/A"
            if isinstance(addr, dict):
                parts = []
                # Street line
                street = addr.get("street") or addr.get("line1") or addr.get("address")
                if street:
                    parts.append(street.strip())
                if addr.get("line2"):
                    parts.append(addr.get("line2").strip())
                
                # Suburb/State/Postcode line
                suburb = addr.get("suburb") or addr.get("city")
                state = addr.get("state")
                postcode = addr.get("postcode") or addr.get("zip")
                
                city_parts = [x.strip() for x in [suburb, state, postcode] if x]
                if city_parts:
                    parts.append(" ".join(city_parts))
                
                return " | ".join(parts) if parts else "N/A"
            return "N/A"

        writer.writerow(["Company", customer.get("company") or customer.get("company_name") or "N/A"])
        writer.writerow(["ABN/ACN", customer.get("abn") or customer.get("acn") or "N/A"])
        
        # Properly formatted addresses
        site_addr = customer.get("site_address") or customer.get("address")
        billing_addr = customer.get("billing_address")
        
        writer.writerow(["Site Address", format_address(site_addr)])
        writer.writerow(["Billing Address", format_address(billing_addr)])
        
        writer.writerow(["Main Contact", customer.get("main_contact_name") or customer.get("contact_name") or "N/A"])
        writer.writerow(["Email", customer.get("main_contact_email") or customer.get("email") or "N/A"])
        writer.writerow(["Phone", customer.get("main_contact_number") or customer.get("phone") or "N/A"])
        writer.writerow(["Type", customer.get("type", "Business")])
        writer.writerow([])

        # === SAVINGS SUMMARY ===
        writer.writerow(["SAVINGS SUMMARY (ex GST)"])
        current = quote.get("current_spend_ex", 0.0)
        proposed = quote.get("new_monthly_ex", 0.0)
        saving = quote.get("monthly_saving_ex", 0.0)
        
        writer.writerow(["Current monthly spend", f"${current:.2f}"])
        writer.writerow(["New monthly recurring", f"${proposed:.2f}"])
        writer.writerow(["Monthly saving", f"${saving:.2f}"])
        writer.writerow(["24-month saving", f"${saving * 24:.2f}"])
        writer.writerow([])

        # === QUOTE LINE ITEMS ===
        writer.writerow(["QUOTE LINE ITEMS"])
        writer.writerow(["SKU", "Description", "Quantity", "Unit Price (ex GST)", "Total (ex GST)", "Cadence", "HaaS Term"])

        monthly_total = 0.0
        once_off_total = 0.0

        for line in quote.get("selected_lines", []):
            qty = line.get("qty", 1)
            unit_ex = line.get("unit_ex", 0.0)
            total_ex = qty * unit_ex
            sku = line.get("sku", "CUSTOM")
            desc = line.get("desc", "Service")
            cadence = line.get("cadence", "monthly").capitalize()
            haas = line.get("haas_term", "")

            writer.writerow([
                sku,
                desc,
                qty,
                f"${unit_ex:.2f}",
                f"${total_ex:.2f}",
                cadence,
                haas or ""
            ])

            if line.get("cadence", "monthly").lower() == "monthly":
                monthly_total += total_ex
            else:
                once_off_total += total_ex

        writer.writerow([])
        writer.writerow(["MONTHLY RECURRING TOTAL (ex GST)", f"${monthly_total:.2f}"])
        writer.writerow(["ONCE-OFF TOTAL (ex GST)", f"${once_off_total:.2f}"])
        writer.writerow([])
        writer.writerow(["Quote Status", quote.get("status", "Draft")])
        writer.writerow(["Valid for 30 days from issue date"])
        writer.writerow(["Terms & Conditions apply • NBN availability subject to NBNCO assessment"])

    return FileResponse(
        path,
        media_type="text/csv",
        filename=f"QuoteFull_{quote_id[:8].upper()}.csv"
    )
# @app.post("/send-email/{quote_id}")
# async def send_email(quote_id: str, to_email: str = Form(...)):
#     quote = await quotes_collection.find_one({"_id": quote_id})
#     if not quote:
#         raise HTTPException(404)
#     quote["id"] = quote_id  # For PDF
#     # Generate email content with Grok
#     messages = [{"role": "system", "content": EMAIL_PROMPT}]
#     messages.append({"role": "user", "content": json.dumps(quote)})
#     try:
#         response = client.chat.completions.create(
#             model="grok-3-latest",
#             messages=messages,
#             response_format={"type": "json_object"},
#             max_tokens=1000,
#         )
#         email_content = json.loads(response.choices[0].message.content)
#         subject = email_content["subject"]
#         body = email_content["body"]
#     except Exception as e:
#         raise HTTPException(500, f"Grok email generation failed: {str(e)}") from e
#     pdf_path = generate_pdf(quote)
#     msg = MIMEMultipart()
#     msg["From"] = FROM_EMAIL
#     msg["To"] = to_email
#     msg["Subject"] = subject
#     msg.attach(MIMEText(body, "plain"))
#     with open(pdf_path, "rb") as f:
#         attach = MIMEApplication(f.read(), _subtype="pdf")
#         attach.add_header("Content-Disposition", "attachment", filename=f"Quote_{quote_id[:8].upper()}.pdf")
#         msg.attach(attach)
#     if os.path.exists(TCS_PDF_PATH):
#         with open(TCS_PDF_PATH, "rb") as f:
#             attach = MIMEApplication(f.read(), _subtype="pdf")
#             attach.add_header("Content-Disposition", "attachment", filename="Standard_TCs.pdf")
#             msg.attach(attach)
#     try:
#         with smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT)) as server:
#             server.starttls()
#             server.login(SMTP_USER, SMTP_PASS)
#             server.send_message(msg)
#     except Exception as e:
#         raise HTTPException(500, f"Email sending failed: {str(e)}") from e
#     await quotes_collection.update_one({"_id": quote_id}, {"$set": {"status": "Sent"}})
#     return {"message": "Email sent successfully"}
@app.post("/send-email/{quote_id}")
async def send_email(quote_id: str, to_email: str = Form(...)):
    quote = await quotes_collection.find_one({"_id": quote_id})
    if not quote:
        raise HTTPException(404, "Quote not found")
    # Prepare minimal customer info for personalization
    cust = quote.get("raw_grok_output", {})
    # print(cust)
    customer = cust.customer_info
    print(customer)
    contact_name = (
        customer.get("main_contact_name")
        or customer.get("contact_name")
        or customer.get("billing_contact_name")
        or "Valued Customer"
    )
    company = customer.get("company") or customer.get("company_name") or ""

    # Fixed short subject and body
#     subject = f"Your Telco Quote #{quote_id[:8].upper()}"
#     body = f"""Dear {contact_name},

# Please find your personalised telco quote attached.

# Feel free to reply to this email or give me a call if you have any questions.

# """
    body = f"""Please find your personalised telco quote attached.

Feel free to reply to this email or give me a call if you have any questions.

"""

    # Generate PDF
    quote["id"] = quote_id
    pdf_path = generate_pdf(quote)

    # Build email
    msg = MIMEMultipart()
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    # Attach PDF
    with open(pdf_path, "rb") as f:
        attach = MIMEApplication(f.read(), _subtype="pdf")
        attach.add_header(
            "Content-Disposition",
            "attachment",
            filename=f"Quote_{quote_id[:8].upper()}.pdf"
        )
        msg.attach(attach)

    # Attach T&Cs if exists
    if os.path.exists(TCS_PDF_PATH):
        with open(TCS_PDF_PATH, "rb") as f:
            attach = MIMEApplication(f.read(), _subtype="pdf")
            attach.add_header(
                "Content-Disposition",
                "attachment",
                filename="Standard_TCs.pdf"
            )
            msg.attach(attach)

    # Send email
    try:
        with smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT)) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    except Exception as e:
        raise HTTPException(500, f"Email sending failed: {str(e)}") from e

    # Update status
    await quotes_collection.update_one(
        {"_id": quote_id},
        {"$set": {"status": "Sent"}}
    )

    return {"message": "Email sent successfully"}
@app.get("/")
async def root():
    return {"message": "QUOTEFAST PRO – Full Customer Details + Perfect PDF Match"}

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=7002, reload=True)
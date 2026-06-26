"""Mock site server — serves realistic fake local business websites for tests and CI.

Start with: python seeds/mock_site_server.py  (or: make mock-server)
Listens on http://localhost:8888
"""

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Mock Site Server", description="Fake local business sites for testing")

_MOCK_DIR = Path(__file__).parent / "mock_sites"


def _read(filename: str) -> str:
    return (_MOCK_DIR / filename).read_text(encoding="utf-8")


# ── Dental Practice ───────────────────────────────────────────────────────────


@app.get("/dental/", response_class=HTMLResponse)
def dental_home():
    return _read("dental_practice.html")


@app.get("/dental/services/", response_class=HTMLResponse)
def dental_services():
    return """<!DOCTYPE html><html><head><title>Dental Services | Sunrise Dental</title>
<script type="application/ld+json">{"@type":"Dentist","name":"Sunrise Dental"}</script>
</head><body>
<h1>Our Dental Services</h1>
<h2>Preventive Care</h2>
<p>Professional cleanings starting at $99. X-rays from $25 per set.
   Comprehensive exam: $75 for new patients.</p>
<h2>Cosmetic Dentistry</h2>
<p>Professional teeth whitening: $299 per session. Porcelain veneers: $900–$1,500 per tooth.</p>
<h2>Restorative</h2>
<p>Composite fillings: $150–$300. Crowns: $1,000–$1,500. Dental implants: starting at $3,500.</p>
<h2>Orthodontics</h2>
<p>Invisalign: from $3,800 for minor cases; $5,500–$7,000 for comprehensive treatment.</p>
<h2>Emergency Care</h2>
<p>Same-day emergency appointments available. Emergency exam fee: $50 (applied toward treatment).
   After-hours emergency line: (512) 555-0199.</p>
<a href="/dental/">Home</a> <a href="/dental/pricing/">Pricing</a>
</body></html>"""


@app.get("/dental/pricing/", response_class=HTMLResponse)
def dental_pricing():
    return """<!DOCTYPE html><html><head><title>Pricing | Sunrise Dental</title></head><body>
<h1>Transparent Pricing</h1>
<h2>Preventive</h2>
<p>Cleaning &amp; exam: $174 (new patient special). Annual cleanings (2x): $198/year.</p>
<h2>Restorative</h2>
<p>Simple filling: $150. Complex filling: $300. Root canal: $800–$1,200. Crown: $1,200.</p>
<h2>Cosmetic</h2>
<p>Whitening: $299 in-office. Take-home kit: $199. Veneers: $950 per tooth.</p>
<h2>Insurance</h2>
<p>We accept Delta Dental, Aetna, Cigna, and United Concordia. We also offer
   CareCredit financing with 0% APR for 12 months.</p>
<a href="/dental/">Home</a> <a href="/dental/services/">Services</a>
</body></html>"""


@app.get("/dental/about/", response_class=HTMLResponse)
def dental_about():
    return """<!DOCTYPE html><html><head><title>About | Sunrise Dental</title></head><body>
<h1>About Sunrise Dental</h1>
<h2>Our Story</h2>
<p>Founded in 2005 by Dr. Sarah Mitchell, DDS. Board-certified in General Dentistry.
   Graduate of UT Health San Antonio School of Dentistry.</p>
<h2>Our Team</h2>
<p>Dr. Sarah Mitchell — General &amp; Cosmetic Dentist, 20+ years experience.</p>
<p>Dr. Kevin Park — Orthodontist, Invisalign Platinum Provider.</p>
<h2>Accreditations</h2>
<p>Member: American Dental Association, Texas Dental Association.
   Austin Business Journal "Best Dentist" 2022, 2023.</p>
<a href="/dental/">Home</a>
</body></html>"""


@app.get("/dental/faq/", response_class=HTMLResponse)
def dental_faq():
    return """<!DOCTYPE html><html><head><title>FAQ | Sunrise Dental</title></head><body>
<h1>Frequently Asked Questions</h1>
<h2>Do you accept insurance?</h2>
<p>Yes, we accept most major dental insurance plans including Delta Dental, Aetna, and Cigna.</p>
<h2>What are your hours?</h2>
<p>Mon–Fri 8:00 AM–6:00 PM, Sat 9:00 AM–2:00 PM. Emergency appointments available same-day.</p>
<h2>Do you offer payment plans?</h2>
<p>Yes, we offer 0% APR financing through CareCredit for 12 months.</p>
<a href="/dental/">Home</a>
</body></html>"""


@app.get("/dental/contact/", response_class=HTMLResponse)
def dental_contact():
    return """<!DOCTYPE html><html><head><title>Contact | Sunrise Dental</title></head><body>
<h1>Contact Us</h1>
<p>Phone: (512) 555-0100</p>
<p>Address: 1234 Oak Street, Austin, TX 78701</p>
<p>Email: hello@sunrisedental.example.com</p>
<a href="/dental/">Home</a>
</body></html>"""


# ── Home Services ─────────────────────────────────────────────────────────────


@app.get("/home-services/", response_class=HTMLResponse)
def home_services_home():
    return _read("home_services.html")


@app.get("/home-services/services/", response_class=HTMLResponse)
def home_services_services():
    return """<!DOCTYPE html><html><head><title>Services | ProFix Home Services</title>
<script type="application/ld+json">{"@type":"HomeAndConstructionBusiness","name":"ProFix"}</script>
</head><body>
<h1>Our Services</h1>
<h2>Plumbing</h2>
<p>Leak detection and repair, drain cleaning ($99–$299), water heater replacement ($800–$1,800),
   pipe burst repair, sewer line inspection.</p>
<h2>HVAC</h2>
<p>AC tune-up: $129. AC repair: $200–$600 depending on part. New AC installation: $3,500–$7,000.
   Furnace repair: $150–$450. Duct cleaning: $299 for standard home.</p>
<h2>Electrical</h2>
<p>Panel upgrade 200A: $1,800–$3,000. EV charger installation: $500–$1,500.
   Electrical troubleshooting: $125 minimum.</p>
<a href="/home-services/">Home</a>
</body></html>"""


@app.get("/home-services/service-area/", response_class=HTMLResponse)
def home_services_area():
    return """<!DOCTYPE html><html><head><title>Service Area | ProFix</title></head><body>
<h1>Our Service Area</h1>
<p>We proudly serve the entire Dallas-Fort Worth metroplex including:</p>
<ul>
<li>Dallas</li><li>Fort Worth</li><li>Plano</li><li>Irving</li>
<li>Frisco</li><li>McKinney</li><li>Arlington</li><li>Garland</li><li>Mesquite</li>
</ul>
<p>Travel fee may apply for locations more than 30 miles from our Dallas headquarters.</p>
<a href="/home-services/">Home</a>
</body></html>"""


# ── Law Firm ──────────────────────────────────────────────────────────────────


@app.get("/law-firm/", response_class=HTMLResponse)
def law_firm_home():
    return _read("law_firm.html")


@app.get("/law-firm/practice-areas/", response_class=HTMLResponse)
def law_firm_practice():
    return """<!DOCTYPE html><html><head><title>Practice Areas | Mitchell & Associates</title>
<script type="application/ld+json">{"@type":"LegalService","name":"Mitchell & Associates"}</script>
</head><body>
<h1>Our Practice Areas</h1>
<h2>Personal Injury</h2>
<p>We handle auto accidents, slip and fall, trucking accidents, and wrongful death.
   We work on contingency: no fees unless we recover money for you. Our standard
   contingency fee is 33% of the settlement (40% if case goes to trial).</p>
<h2>Family Law</h2>
<p>Divorce (contested and uncontested), child custody, child support, spousal maintenance.
   Uncontested divorce flat fee: $1,500. Hourly rate for contested cases: $350/hour.</p>
<h2>Estate Planning</h2>
<p>Simple will: $350. Trust package: $1,200. Healthcare directive + POA bundle: $500.</p>
<h2>Criminal Defense</h2>
<p>DWI defense, misdemeanor charges, felony cases. Free initial consultation.
   Flat fee arrangements available for most misdemeanor cases starting at $2,500.</p>
<a href="/law-firm/">Home</a>
</body></html>"""


@app.get("/law-firm/team/", response_class=HTMLResponse)
def law_firm_team():
    return """<!DOCTYPE html><html><head><title>Our Team | Mitchell & Associates</title></head><body>
<h1>Our Attorneys</h1>
<h2>James Mitchell, JD</h2>
<p>Founding Partner. University of Texas School of Law, 1997.
   Board Certified in Personal Injury Trial Law (Texas Board of Legal Specialization).
   25+ years of trial experience. $50 million+ recovered for clients.</p>
<h2>Elena Rodriguez, JD</h2>
<p>Associate Attorney. South Texas College of Law, 2014.
   10 years family law experience. Fluent in English and Spanish.</p>
<h2>Marcus Chen, JD</h2>
<p>Associate Attorney. University of Houston Law Center, 2018.
   Specializes in criminal defense and DWI cases.</p>
<a href="/law-firm/">Home</a>
</body></html>"""


@app.get("/law-firm/faq/", response_class=HTMLResponse)
def law_firm_faq():
    return """<!DOCTYPE html><html><head><title>FAQ | Mitchell & Associates</title></head><body>
<h1>Frequently Asked Questions</h1>
<h2>Do you offer free consultations?</h2>
<p>Yes. All initial consultations are free and last up to 60 minutes.</p>
<h2>What is a contingency fee?</h2>
<p>You pay nothing upfront. We receive 33% of the settlement if we win.
   If we don't win, you owe us nothing.</p>
<h2>How long do personal injury cases take?</h2>
<p>Most cases settle within 6–18 months. Complex cases may take 2–3 years.</p>
<a href="/law-firm/">Home</a>
</body></html>"""


if __name__ == "__main__":
    port = int(os.environ.get("MOCK_PORT", 8888))
    uvicorn.run(app, host="0.0.0.0", port=port)

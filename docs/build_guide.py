"""Build the KokkaCo-styled jobagent user guide (ReportLab, letter portrait)."""
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame, KeepTogether,
                                NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle)

OUT = sys.argv[1]

# --- KokkaCo palette (sampled from the Strategy One-Pager) -------------------
NAVY = colors.HexColor("#12324a")
BLUE = colors.HexColor("#2f6b9a")
TEAL = colors.HexColor("#2a8c82")
GREEN = colors.HexColor("#27845b")
CYAN = colors.HexColor("#42a5c6")
ORANGE = colors.HexColor("#d77a2b")
PANEL = colors.HexColor("#f3f6f8")
BORDER = colors.HexColor("#d8e2e8")
GREEN_T = colors.HexColor("#eaf5f0")
ORANGE_T = colors.HexColor("#fff4e8")
INK = colors.HexColor("#1f2a33")
MUTED = colors.HexColor("#5f6f7c")

W, H = letter
M = 0.6 * inch
CW = W - 2 * M

# --- Type ----------------------------------------------------------------------
def S(name, **kw):
    base = dict(fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)

body = S("body")
small = S("small", fontSize=8.5, leading=11.5, textColor=MUTED)
label = S("label", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=BLUE,
          spaceBefore=4, spaceAfter=6)
h_step = S("hstep", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=NAVY)
h_sub = S("hsub", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=NAVY, spaceAfter=2)
card_t = S("cardt", fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=NAVY)
code = S("code", fontName="Courier", fontSize=8.6, leading=11.6, textColor=INK)
code_c = S("codec", fontName="Courier", fontSize=8.6, leading=11.6, textColor=MUTED)
center_small = S("cs", fontSize=8, leading=10, textColor=MUTED, alignment=TA_CENTER)
center_bold = S("cb", fontName="Helvetica-Bold", fontSize=9.5, leading=12, textColor=NAVY,
                alignment=TA_CENTER)
cell = S("cell", fontSize=8.8, leading=11.8)
cell_b = S("cellb", fontName="Helvetica-Bold", fontSize=8.8, leading=11.8, textColor=NAVY)
cell_h = S("cellh", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=colors.white)

P = Paragraph


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- Building blocks ----------------------------------------------------------------
class Circle(Flowable):
    """Numbered step circle, as in the one-pager's flywheel."""

    def __init__(self, n, color=BLUE, r=13):
        super().__init__()
        self.n, self.color, self.r = str(n), color, r
        self.width = self.height = 2 * r

    def draw(self):
        c = self.canv
        c.setFillColor(self.color)
        c.circle(self.r, self.r, self.r, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", self.r * 0.95)
        c.drawCentredString(self.r, self.r - self.r * 0.33, self.n)


class Arrow(Flowable):
    def __init__(self, w=16, h=26):
        super().__init__()
        self.width, self.height = w, h

    def draw(self):
        c = self.canv
        c.setStrokeColor(BORDER)
        c.setFillColor(MUTED)
        y = self.height / 2
        c.setLineWidth(1.2)
        c.line(1, y, self.width - 5, y)
        p = c.beginPath()
        p.moveTo(self.width - 1, y)
        p.lineTo(self.width - 6, y + 3.5)
        p.lineTo(self.width - 6, y - 3.5)
        p.close()
        c.drawPath(p, stroke=0, fill=1)


def section(text):
    return P(text.upper(), label)


def panel(flowables, bg=PANEL, border=BORDER, pad=10, width=CW, accent=None):
    t = Table([[flowables]], colWidths=[width])
    st = [("BACKGROUND", (0, 0), (-1, -1), bg),
          ("BOX", (0, 0), (-1, -1), 0.6, border),
          ("LEFTPADDING", (0, 0), (-1, -1), pad), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
          ("TOPPADDING", (0, 0), (-1, -1), pad - 2), ("BOTTOMPADDING", (0, 0), (-1, -1), pad)]
    if accent is not None:
        st.append(("LINEBEFORE", (0, 0), (0, -1), 3, accent))
    t.setStyle(TableStyle(st))
    return t


def codeblock(lines):
    """Monospace command block. A line starting with '#' renders as a comment."""
    paras = []
    for ln in lines:
        if "  #" in ln:
            cmd, cmt = ln.split("  #", 1)
            paras.append(P(esc(cmd).replace(" ", "&nbsp;") + "&nbsp;&nbsp;"
                           f"<font color='#5f6f7c'>#{esc(cmt)}</font>", code))
        elif ln.startswith("#"):
            paras.append(P(esc(ln), code_c))
        else:
            paras.append(P(esc(ln).replace("  ", "&nbsp;&nbsp;"), code))
    t = Table([[p] for p in paras], colWidths=[CW - 20])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LINEBEFORE", (0, 0), (0, -1), 3, TEAL),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 1.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
    ]))
    return t


def step(n, title, time_note, intro, *content, color=BLUE):
    head = Table([[Circle(n, color), P(title, h_step), P(time_note, small)]],
                 colWidths=[34, CW - 34 - 110, 110])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    parts = [head, Spacer(1, 4), P(intro, body), Spacer(1, 6)]
    for c in content:
        parts += [c, Spacer(1, 6)]
    return parts


def bullets(items, style=body, color="#2f6b9a"):
    return [P(f"<font color='{color}'>&#8226;</font>&nbsp;&nbsp;{i}", style) for i in items]


def callout(title, text, kind="tip"):
    bg, acc = {"tip": (GREEN_T, GREEN), "warn": (ORANGE_T, ORANGE)}[kind]
    color = "#27845b" if kind == "tip" else "#d77a2b"
    return panel([P(f"<font color='{color}'><b>{title.upper()}</b></font>", S("ct", fontSize=8,
                    leading=10, spaceAfter=3)), P(text, body)], bg=bg, border=bg, accent=acc)


def grid(rows, widths, header=True):
    data = []
    for i, r in enumerate(rows):
        if header and i == 0:
            data.append([P(c, cell_h) for c in r])
        else:
            data.append([P(c, cell_b if j == 0 else cell) for j, c in enumerate(r)])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.5, BORDER),
          ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
          ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    for i in range(1 if header else 0, len(rows)):
        if (i % 2 == 0):
            st.append(("BACKGROUND", (0, i), (-1, i), PANEL))
    t.setStyle(TableStyle(st))
    return t


# --- Page chrome -----------------------------------------------------------------
def cover_page(c, doc):
    c.saveState()
    band = 1.55 * inch
    c.setFillColor(NAVY)
    c.rect(0, H - band, W, band, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(M, H - 0.72 * inch, "KOKKACO JOBAGENT")
    c.setFont("Helvetica", 11.5)
    c.setFillColor(colors.HexColor("#c9d6e0"))
    c.drawString(M, H - 1.0 * inch, "User guide: from setup to your first tailored application")
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.white)
    c.drawRightString(W - M, H - 0.62 * inch, "STEP-BY-STEP OPERATING GUIDE")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#c9d6e0"))
    c.drawRightString(W - M, H - 0.84 * inch, "Discover  |  Evaluate  |  Tailor  |  Apply")
    c.drawRightString(W - M, H - 1.04 * inch, "Version 0.1  |  October 2026")
    footer(c, doc)
    c.restoreState()


def inner_page(c, doc):
    c.saveState()
    band = 0.5 * inch
    c.setFillColor(NAVY)
    c.rect(0, H - band, W, band, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(M, H - 0.32 * inch, "KOKKACO JOBAGENT")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#c9d6e0"))
    c.drawRightString(W - M, H - 0.32 * inch, "User guide")
    footer(c, doc)
    c.restoreState()


def footer(c, doc):
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.6)
    c.line(M, 0.55 * inch, W - M, 0.55 * inch)
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillColor(MUTED)
    c.drawString(M, 0.38 * inch,
                 "Internal tool guide. jobagent never submits an application without your review.")
    c.drawRightString(W - M, 0.38 * inch, f"Page {doc.page}")


# --- Content ---------------------------------------------------------------------
story = [NextPageTemplate("inner")]

# ===== Page 1: overview =====
story.append(panel([P("<b><font color='#12324a'>WHAT IT DOES</font></b>&nbsp;&nbsp; jobagent finds "
                      "open roles at the companies you choose, scores how well each one fits you, "
                      "rewrites your resume toward the best ones <b>using only what is true</b>, and "
                      "fills the application form for you to review. You stay in control of every "
                      "submission.", body)], bg=colors.HexColor("#eef3f8"), border=colors.HexColor("#eef3f8")))
story.append(Spacer(1, 10))
story.append(section("The workflow at a glance"))

flow = [("1", "Scan", "Find new roles at your companies", BLUE),
        ("2", "Triage", "Score each role 1 to 5", CYAN),
        ("3", "Shortlist", "Review the ranked list", TEAL),
        ("4", "Tailor", "Truthful resume PDF per role", GREEN),
        ("5", "Apply", "Form filled; you submit", ORANGE)]
cells, widths = [], []
for i, (n, t, d, col) in enumerate(flow):
    box = Table([[Circle(n, col, 14)], [P(t, center_bold)], [P(d, center_small)]],
                colWidths=[86])
    box.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"),
                             ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                             ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                             ("TOPPADDING", (0, 0), (-1, -1), 4),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    cells.append(box)
    widths.append(90)
    if i < len(flow) - 1:
        cells.append(Arrow())
        widths.append(16)
ft = Table([cells], colWidths=widths)
ft.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
story += [ft, Spacer(1, 12)]

# two-column: principles + what you need
left = [section("Operating principles")] + bullets([
    "<b>Truthful by design.</b> The tool may rephrase your real experience in the job's language. "
    "It cannot add skills, tools or numbers you never had. Code checks every rewrite and reverts "
    "anything that fails.",
    "<b>You submit.</b> Form filling runs as a dry run in a visible browser. It stops at captchas "
    "and never ticks legal attestation boxes.",
    "<b>Cheap filters first.</b> Deal-breakers (no visa sponsorship, clearance, years required) are "
    "checked in code before any AI call is spent.",
    "<b>Nothing is lost.</b> Every job seen is stored once, with the reason it was kept or filtered.",
])
right = [section("Already installed on this machine")] + [grid([
    ["Component", "Status"],
    ["Claude CLI (AI engine)", "Ready, no API key needed"],
    ["LaTeX engine (tectonic)", "Ready, builds the PDFs"],
    ["Playwright + Chrome", "Ready, fills forms"],
    ["jobagent command", "Installed in ~/.local/bin"],
], [1.55 * inch, 1.55 * inch])] + [Spacer(1, 8), P("Confirm at any time with:", small),
                                   Spacer(1, 3)]
cmd_small = Table([[P("jobagent doctor", code)]], colWidths=[3.1 * inch])
cmd_small.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                               ("LINEBEFORE", (0, 0), (0, -1), 3, TEAL),
                               ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                               ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
right.append(cmd_small)
two = Table([[left, right]], colWidths=[CW * 0.52, CW * 0.48])
two.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                         ("LEFTPADDING", (0, 0), (-1, -1), 0),
                         ("RIGHTPADDING", (0, 0), (0, 0), 16), ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
story += [two, Spacer(1, 10)]

story.append(section("Where everything lives"))
story.append(P("Project folder: <font name='Courier'>~/Documents/KokkaCo_Corperate_Strategy/KokkaStrat/"
               "jobagent</font>. Open a terminal there before running any command.", body))
story.append(Spacer(1, 6))
story.append(grid([
    ["File / folder", "What it is", "You edit it?"],
    ["jobagent/profile/resume_content.yaml", "Your master resume as structured data", "Yes: step 1"],
    ["jobagent/profile/standard_answers.yaml", "Answers every application form asks", "Yes: step 2"],
    ["jobagent/profile/search.yaml", "Companies, filters and target roles", "Yes: step 3"],
    ["data/generated/&lt;Company_Title&gt;/", "Tailored PDFs and reports per job", "No: output"],
    ["data/jobagent.db", "Tracker database (jobs, scores, applications)", "No: managed"],
], [2.75 * inch, 2.85 * inch, CW - 5.6 * inch]))

story.append(PageBreak())

# ===== Setup steps =====
story.append(P("PART 1  |  ONE-TIME SETUP", S("part", fontName="Helvetica-Bold", fontSize=9,
                                               textColor=MUTED, spaceAfter=10)))
story.append(callout("Time to first result",
                     "About 1.5 hours of one-time setup, mostly writing your resume file. After "
                     "that, about 15 minutes a day to scan, review the shortlist and tailor."))
story.append(Spacer(1, 10))

story += step(1, "Write your master resume", "30 to 60 minutes",
              "Open <font name='Courier'>jobagent/profile/resume_content.yaml</font> in a text "
              "editor and replace every placeholder with your real details. This is your "
              "<b>master</b>. The tool never changes it; it creates a tailored copy for each job.",
              codeblock([
                  "name: \"Your Full Name\"",
                  "headline: \"Strategy & Operations | Ex-Consulting\"",
                  "email: \"you@example.com\"",
                  "experience:",
                  "  - company: \"KokkaCo\"",
                  "    title: \"Strategy Lead\"",
                  "    start: \"2024\"",
                  "    end: \"Present\"",
                  "    bullets:",
                  "      - id: \"kokka-1\"          # short, unique, never reuse",
                  "        text: \"Built a 3-statement model that informed a $10M decision.\"",
              ]),
              callout("Two rules that make tailoring work",
                      "<b>Include everything true</b>, even bullets you would normally cut. The "
                      "tool can only select and rephrase what is in this file. <b>Put real numbers in "
                      "the bullets.</b> A tailored bullet is never allowed to add a number that is "
                      "not already in the original."),
              P("Check that the file loads correctly:", body),
              codeblock(["python3 -c \"from jobagent.profile_loader import load_resume; "
                         "print(load_resume().name)\""]))

story.append(Spacer(1, 4))
story += step(2, "Fill in your standard answers", "10 minutes",
              "Open <font name='Courier'>jobagent/profile/standard_answers.yaml</font>. These are "
              "the questions every application form repeats. The form filler uses them, and your "
              "sponsorship answer also tells the evaluator whether to skip roles that will not "
              "sponsor a visa.",
              grid([
                  ["Section", "What to enter"],
                  ["personal", "Name, email, phone, city, state, country, LinkedIn, website"],
                  ["work_authorization", "authorized_to_work (true/false), requires_sponsorship "
                                         "(true/false), visa_status"],
                  ["preferences", "Salary expectation (or leave blank), start date, relocation, "
                                  "Remote / Hybrid / Onsite"],
                  ["eeo", "Gender, ethnicity, veteran, disability. \"Decline to self-identify\" is fine."],
              ], [1.6 * inch, CW - 1.6 * inch]))

story.append(CondPageBreak(4.5 * inch))
story += step(3, "Choose companies and target roles", "15 minutes",
              "Open <font name='Courier'>jobagent/profile/search.yaml</font>. The values there "
              "now are examples only. Replace them with your own.",
              P("<b>Adding a company.</b> Open its careers page, click any job, and read the web "
                "address:", body),
              grid([
                  ["If the job URL looks like", "Add this line under companies:"],
                  ["job-boards.greenhouse.io/<b>stripe</b>/jobs/...",
                   "<font name='Courier'>{name: Stripe, ats: greenhouse, board: stripe}</font>"],
                  ["jobs.lever.co/<b>palantir</b>/...",
                   "<font name='Courier'>{name: Palantir, ats: lever, board: palantir}</font>"],
                  ["jobs.ashbyhq.com/<b>ramp</b>/...",
                   "<font name='Courier'>{name: Ramp, ats: ashby, board: ramp}</font>"],
              ], [2.6 * inch, CW - 2.6 * inch]),
              grid([
                  ["Setting", "What it controls"],
                  ["titles", "Words a job title must include (any one) or must not include"],
                  ["locations", "Allowed and blocked locations; remote roles pass by default"],
                  ["max_posting_age_days", "Ignore postings older than this"],
                  ["hard_filters", "Your real years of experience, and whether you hold a security "
                                   "clearance"],
                  ["targets", "The 2 to 4 kinds of role you actually want. A job matching none of "
                              "them is capped at a low score."],
              ], [1.6 * inch, CW - 1.6 * inch]),
              callout("Workday and other sites",
                      "Workday career sites cannot be scanned yet. You can still paste any job URL "
                      "into evaluate or tailor (Part 2).", kind="warn"))

story.append(Spacer(1, 8))
story.append(section("Setup checklist: before you continue"))
check_items = [
    "Every placeholder in resume_content.yaml replaced; each bullet has a unique id",
    "Real numbers written into the bullets that have them",
    "The load check from step 1 prints your name",
    "Work authorization and sponsorship answers are correct in standard_answers.yaml",
    "search.yaml lists your companies, not the examples",
    "targets describes the 2 to 4 roles you actually want",
    "hard_filters.years_experience is your real total",
    "jobagent doctor shows no red items",
]
class Box(Flowable):
    """Empty checkbox to tick by hand on a printout."""

    def __init__(self, s=9):
        super().__init__()
        self.width = self.height = s

    def draw(self):
        self.canv.setStrokeColor(BLUE)
        self.canv.setFillColor(colors.white)
        self.canv.setLineWidth(1)
        self.canv.rect(0, 0, self.width, self.height, stroke=1, fill=1)


chk = Table([[Box(), P(i, body)] for i in check_items], colWidths=[18, CW - 38])
chk.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                         ("LEFTPADDING", (0, 0), (-1, -1), 0),
                         ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]))
story.append(panel([chk]))

story.append(PageBreak())

# ===== First run =====
story.append(P("PART 2  |  YOUR FIRST RUN", S("part2", fontName="Helvetica-Bold", fontSize=9,
                                              textColor=MUTED, spaceAfter=10)))
story += step(4, "Test on one job you know well", "10 minutes",
              "Pick a posting you understand, ideally one you would be strong for, so you can "
              "judge whether the output makes sense. Run:",
              codeblock([
                  "jobagent evaluate \"<job url>\"   # fit score with evidence per requirement",
                  "jobagent tailor \"<job url>\"     # tailored resume PDF + report",
              ]),
              P("Then open <font name='Courier'>data/generated/&lt;Company_Title&gt;/</font> and "
                "review three things:", body),
              grid([
                  ["Output", "What to look for"],
                  ["resume.pdf", "Your tailored resume. Read every bullet as a recruiter would."],
                  ["Gap list (report.json)", "What the job wants that your resume does not support. "
                                             "Do not claim these unless they are genuinely true."],
                  ["Reverted bullets", "Rewrites that failed the truthfulness check. Your original "
                                       "text was kept instead."],
              ], [1.7 * inch, CW - 1.7 * inch]),
              callout("If the evaluation feels wrong",
                      "The fix is almost always in your inputs: a missing bullet in "
                      "resume_content.yaml, or targets in search.yaml that do not describe what you "
                      "want. Edit them and run evaluate again."))

story.append(Spacer(1, 4))
story.append(section("How a job is scored"))
story.append(P("Evaluation runs in four stages, cheapest first, so the score is consistent from run "
               "to run:", body))
story.append(Spacer(1, 6))
story.append(grid([
    ["Stage", "What happens"],
    ["1. Hard stops", "Deal-breakers read from the job text (no sponsorship when you need it, "
                      "clearance, far more years than you have). Any hit means skip, with no AI cost."],
    ["2. Requirements", "The AI lists the job's requirements and how important each is, "
                        "<b>before</b> it sees your resume."],
    ["3. Evidence", "Each requirement is marked stated (must cite a real bullet), inferred, or none."],
    ["4. Score", "Weighted 1 to 5: resume match 40%, target fit 30%, level 15%, pay 15%. Capped "
                 "at 3.4 if a critical requirement is unmet."],
], [1.3 * inch, CW - 1.3 * inch]))
story.append(Spacer(1, 8))
bands = Table([[
    panel([P("<font color='#27845b'><b>4.0 AND ABOVE</b></font>", S("b1", fontSize=8)),
           P("<b>Apply.</b> Tailor and apply.", body)], bg=GREEN_T, border=GREEN_T, width=CW / 3 - 6),
    panel([P("<font color='#d77a2b'><b>3.5 TO 3.9</b></font>", S("b2", fontSize=8)),
           P("<b>Consider.</b> Needs a clear reason.", body)], bg=ORANGE_T, border=ORANGE_T,
          width=CW / 3 - 6),
    panel([P("<font color='#5f6f7c'><b>BELOW 3.5</b></font>", S("b3", fontSize=8)),
           P("<b>Skip.</b> Spend the time elsewhere.", body)], width=CW / 3 - 6),
]], colWidths=[CW / 3] * 3)
bands.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
story.append(bands)

story.append(PageBreak())

# ===== Daily loop =====
story.append(P("PART 3  |  THE DAILY ROUTINE", S("part3", fontName="Helvetica-Bold", fontSize=9,
                                                 textColor=MUTED, spaceAfter=10)))
story += step(5, "Run the daily loop", "About 15 minutes a day",
              "Once setup is done, this is the whole routine:",
              codeblock([
                  "jobagent scan                 # find new roles at your companies",
                  "jobagent triage --limit 10    # score them (about 2 AI calls each)",
                  "jobagent jobs                 # ranked shortlist, score 3.5 and up",
                  "jobagent jobs --show <url>    # full breakdown for one role",
                  "jobagent tailor <url>         # tailored PDF for the ones worth it",
                  "jobagent apply <url>          # fill the form; you review and submit",
              ]),
              callout("Your first scan",
                      "The first scan queues every role currently open, so run triage a few times "
                      "to work through the backlog. After that, each scan brings in only roles "
                      "posted since the last one."),
              color=TEAL)

story += step(6, "Apply with a human check", "5 minutes per application",
              "<font name='Courier'>jobagent apply &lt;url&gt;</font> opens the application in a "
              "visible Chrome window and fills it from your standard answers, uploading the "
              "tailored PDF. Greenhouse forms are supported today.",
              *bullets([
                  "<b>Review every field.</b> The terminal lists sensitive answers (work authorization, "
                  "salary, EEO) and any questions it could not answer.",
                  "<b>Tick attestation boxes yourself.</b> The tool never ticks \"I certify...\" boxes.",
                  "<b>Click Submit yourself</b>, then press Enter in the terminal to close the browser.",
                  "Use <font name='Courier'>--live</font> only once you fully trust the fills. It "
                  "still asks for confirmation and still stops at captchas.",
              ]),
              color=ORANGE)

story.append(PageBreak())
story.append(P("PART 4  |  REFERENCE", S("part4", fontName="Helvetica-Bold", fontSize=9,
                                         textColor=MUTED, spaceAfter=10)))
story.append(section("Command reference"))
story.append(grid([
    ["Command", "What it does"],
    ["<font name='Courier'>jobagent doctor</font>", "Checks the AI engine, LaTeX, browser and data folder"],
    ["<font name='Courier'>jobagent scan [-c Company]</font>", "Polls job boards in search.yaml; "
                                                               "-c limits to one company"],
    ["<font name='Courier'>jobagent triage [--limit N]</font>", "Scores up to N queued roles (default 10)"],
    ["<font name='Courier'>jobagent jobs [--min-score X]</font>", "Ranked shortlist; --show &lt;url&gt; "
                                                                  "for details"],
    ["<font name='Courier'>jobagent evaluate &lt;url&gt;</font>", "Scores any single posting"],
    ["<font name='Courier'>jobagent tailor &lt;url&gt;</font>", "Builds the tailored resume PDF and report"],
    ["<font name='Courier'>jobagent apply &lt;url&gt;</font>", "Fills the form (dry run by default)"],
    ["<font name='Courier'>jobagent status</font>", "Lists tracked applications"],
], [2.5 * inch, CW - 2.5 * inch]))

story.append(Spacer(1, 14))
story.append(section("Troubleshooting"))
story.append(grid([
    ["Symptom", "Fix"],
    ["Something will not run", "Run jobagent doctor and fix anything marked red."],
    ["First scan finds 0 new roles", "Title or location filters are too narrow. Widen titles.include "
                                     "or locations.allow in search.yaml."],
    ["A good role was filtered out", "See why: sqlite3 data/jobagent.db \"select title, reason from "
                                     "jobs where status='filtered' limit 20\""],
    ["\"Posting is closed\"", "The role was taken down. The tool will not tailor for dead postings."],
    ["Many bullets reverted", "Your master resume is missing detail. Add the true experience, then "
                              "re-run tailor."],
    ["\"No adapter for ATS\"", "Only Greenhouse forms can be filled today. Use the tailored PDF and "
                               "apply by hand."],
], [1.9 * inch, CW - 1.9 * inch]))

story.append(Spacer(1, 14))
story.append(section("Glossary"))
story.append(grid([
    ["Term", "Meaning"],
    ["ATS", "Applicant tracking system: the software behind a company's job board "
            "(Greenhouse, Lever, Ashby, Workday)."],
    ["Board slug", "The company's short name in its job-board web address, e.g. stripe in "
                   "job-boards.greenhouse.io/stripe."],
    ["Hard stop", "A deal-breaker stated in the job text. The role is skipped without an AI call."],
    ["Gap", "Something the job asks for that your resume does not support. Listed, never invented."],
    ["Dry run", "The form is filled but not submitted. This is the default for apply."],
], [1.3 * inch, CW - 1.3 * inch]))
story.append(Spacer(1, 14))
story.append(KeepTogether([panel([
    P("<font color='#ffffff'><b>GOLDEN RULES</b></font>", S("gr", fontSize=8.5, leading=11,
                                                              spaceAfter=4)),
    P("<font color='#ffffff'>Never claim a gap that is not true.&nbsp;&nbsp;|&nbsp;&nbsp;Always review "
      "before you submit.&nbsp;&nbsp;|&nbsp;&nbsp;Fewer, better-fit applications beat volume.</font>",
      S("gr2", fontSize=9.5, leading=13)),
], bg=NAVY, border=NAVY)]))

# --- Build -------------------------------------------------------------------------
doc = BaseDocTemplate(OUT, pagesize=letter, leftMargin=M, rightMargin=M,
                      title="KokkaCo JobAgent User Guide", author="KokkaCo",
                      subject="Step-by-step guide to the jobagent application")
cover_frame = Frame(M, 0.75 * inch, CW, H - 1.55 * inch - 0.75 * inch - 0.2 * inch, id="cover",
                    leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
inner_frame = Frame(M, 0.75 * inch, CW, H - 0.5 * inch - 0.75 * inch - 0.25 * inch, id="inner",
                    leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
doc.addPageTemplates([PageTemplate("cover", [cover_frame], onPage=cover_page),
                      PageTemplate("inner", [inner_frame], onPage=inner_page)])
doc.build(story)
print("wrote", OUT)

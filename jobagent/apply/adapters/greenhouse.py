"""Greenhouse application-form adapter.

Handles the classic ``boards.greenhouse.io`` form and the newer
``job-boards.greenhouse.io`` layout via a two-pass strategy:

1. Fill the well-known identity fields by stable id/name.
2. Walk every remaining labeled control and resolve it through the answer book.

All DOM interaction is wrapped so a single stubborn field never aborts the run.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..base import BaseAdapter, FillContext, FillReport
from ..fieldmap import is_attestation, match_option

if TYPE_CHECKING:
    from playwright.sync_api import ElementHandle, Page

# Canonical identity fields with their common Greenhouse selectors.
_KNOWN = {
    "first_name": ["#first_name", "input[name='job_application[first_name]']", "input[autocomplete='given-name']"],
    "last_name": ["#last_name", "input[name='job_application[last_name]']", "input[autocomplete='family-name']"],
    "email": ["#email", "input[name='job_application[email]']", "input[type='email']"],
    "phone": ["#phone", "input[name='job_application[phone]']", "input[type='tel']"],
}

_SUBMIT = ["#submit_app", "button[type='submit']", "input[type='submit']"]


def _first_visible(page: "Page", selectors: list[str]):
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return el
        except Exception:
            continue
    return None


def _label_text(page: "Page", el: "ElementHandle") -> str:
    """Best visible label for a control: aria-label, <label for>, placeholder, ancestor."""
    for getter in (
        lambda: el.get_attribute("aria-label"),
        lambda: el.get_attribute("placeholder"),
    ):
        try:
            v = getter()
            if v:
                return v
        except Exception:
            pass
    try:
        fid = el.get_attribute("id")
        if fid:
            lab = page.query_selector(f"label[for='{fid}']")
            if lab:
                t = lab.inner_text()
                if t:
                    return t
    except Exception:
        pass
    try:
        t = el.evaluate("n => (n.closest('label') || n.closest('.field,.form-field'))?.innerText || ''")
        if t:
            return t
    except Exception:
        pass
    return ""


class GreenhouseAdapter(BaseAdapter):
    name = "greenhouse"

    def fill(self, page: "Page", ctx: FillContext, report: FillReport) -> None:
        self._fill_known(page, ctx, report)
        self._upload_resume(page, ctx, report)
        self._walk_fields(page, ctx, report)

    def _fill_known(self, page, ctx, report):
        for key, selectors in _KNOWN.items():
            value = ctx.answers.get(key)
            if not value:
                continue
            el = _first_visible(page, selectors)
            if el is None:
                continue
            try:
                el.fill(value)
                report.note_filled(key, value)
            except Exception:
                report.skipped.append(key)

    def _upload_resume(self, page, ctx, report):
        if not ctx.resume_pdf:
            return
        try:
            file_input = page.query_selector("input[type='file']#resume") \
                or page.query_selector("input[type='file'][name*='resume']") \
                or page.query_selector("input[type='file']")
            if file_input is not None:
                file_input.set_input_files(str(ctx.resume_pdf))
                report.uploaded_resume = True
        except Exception:
            pass

    def _walk_fields(self, page, ctx, report):
        try:
            controls = page.query_selector_all(
                "form input:not([type='hidden']):not([type='file']), form textarea, form select"
            )
        except Exception:
            controls = []
        for el in controls:
            try:
                itype = (el.get_attribute("type") or el.evaluate("n => n.tagName.toLowerCase()"))
            except Exception:
                continue
            if itype in ("submit", "button", "radio", "checkbox"):
                continue  # handled per-group in _walk_choice_groups
            label = _label_text(page, el)
            ans = ctx.answers.resolve(label)
            if ans is None:
                if label.strip():
                    report.skipped.append(label.strip()[:80])
                continue
            if ans.key in report.filled:
                continue
            self._apply(page, el, ans, report)
        self._walk_choice_groups(page, ctx, report)

    def _walk_choice_groups(self, page, ctx, report):
        """Radio/checkbox groups: the question is the fieldset legend (or group label).

        Radios get the polarity-guarded option match. Checkboxes that are legal
        attestations are never ticked — they go to ``needs_review``.
        """
        try:
            groups = page.query_selector_all("form fieldset, form [role='radiogroup'], form [role='group']")
        except Exception:
            groups = []
        for g in groups:
            try:
                question = g.evaluate(
                    "n => (n.querySelector('legend') || n.querySelector('[class*=label]') || {}).innerText"
                    " || n.getAttribute('aria-label') || ''")
                inputs = g.query_selector_all("input[type='radio'], input[type='checkbox']")
            except Exception:
                continue
            if not inputs or not (question or "").strip():
                continue
            question = question.strip()
            kinds = {i.get_attribute("type") for i in inputs}
            if "checkbox" in kinds and is_attestation(question):
                report.needs_review.append(f"attestation (not ticked): {question[:80]}")
                continue
            ans = ctx.answers.resolve(question)
            if ans is None or ans.key in report.filled:
                if ans is None:
                    report.skipped.append(question[:80])
                continue
            labels = [_label_text(page, i) for i in inputs]
            idx = match_option(ans.value, labels)
            if idx is None:
                report.skipped.append(ans.key)
                continue
            try:
                inputs[idx].check()
                self._note(report, ans, labels[idx])
            except Exception:
                report.skipped.append(ans.key)

    @staticmethod
    def _note(report, ans, shown: str):
        report.note_filled(ans.key, shown)
        if ans.sensitive:
            report.needs_review.append(f"{ans.key} = {shown!r}")

    def _apply(self, page, el, ans, report):
        try:
            tag = el.evaluate("n => n.tagName.toLowerCase()")
        except Exception:
            return
        try:
            if tag == "select":
                options = el.evaluate("sel => [...sel.options].map(o => o.text)")
                idx = match_option(ans.value, options)
                if idx is None:
                    report.skipped.append(ans.key)  # never guess a choice
                    return
                el.select_option(index=idx)
                self._note(report, ans, options[idx])
            else:
                if ans.value in ("Yes", "No"):
                    # A bare Yes/No typed into free text is usually wrong — leave it.
                    report.skipped.append(ans.key)
                    return
                maxlen = el.get_attribute("maxlength")
                value = ans.value[: int(maxlen)] if maxlen and maxlen.isdigit() else ans.value
                el.fill(value)
                self._note(report, ans, value)
        except Exception:
            report.skipped.append(ans.key)

    def submit(self, page) -> bool:
        el = _first_visible(page, _SUBMIT)
        if el is None:
            return False
        try:
            el.click()
            return True
        except Exception:
            return False

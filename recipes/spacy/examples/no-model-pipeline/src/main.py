"""A rule-based spaCy pipeline with no model at all, auditing its own tokenisation."""

import re
import threading
import time

import flet as ft
import spacy
from spacy.matcher import PhraseMatcher
from spacy.util import registry

SOURCE = (
    "Dr. Smith invoiced ACME Corp. $4,500.00 on 2026-01-15 via acme.com. "
    "Pay by Friday. A late fee of 1.5% applies after that."
)
PHRASES = {"ACME Corp.": "ORG", "Dr. Smith": "PERSON"}
REPEATS = 5

# spacy.blank() builds the tokenizer, the Vocab and the rule components out of
# spacy/lang/en's ordinary Python source: no model, no download, no file read.
nlp = spacy.blank("en")
nlp.add_pipe("sentencizer")
nlp.add_pipe("entity_ruler").add_patterns(
    [{"label": label, "pattern": phrase} for phrase, label in PHRASES.items()]
)

# Deliberately wrong, and the point of the DISAGREE row: 'acme corp.' tokenises as
# three tokens while the text's 'Corp.' is one, so this matcher finds nothing and
# reports nothing — an empty result is indistinguishable from "the phrase is absent".
lower_matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
lower_matcher.add("ORG", [nlp.make_doc(phrase.lower()) for phrase in PHRASES])

# One pipeline mutating one shared Vocab, one screen, and page.run_thread hands work to a
# pool that can overlap two slider releases: one pass at a time.
lock = threading.Lock()


def residual(rebuilt, text):
    """Characters by which a reassembled string misses `text`; 0 only if they are equal."""
    return sum(a != b for a, b in zip(rebuilt, text)) + abs(len(rebuilt) - len(text))


def token_line(tok):
    """One token as a single display line: text, offset, shape and the flags that are set."""
    flags = ",".join(
        name
        for name, on in (
            ("alpha", tok.is_alpha),
            ("num", tok.like_num),
            ("punct", tok.is_punct),
            ("stop", tok.is_stop),
            ("url", tok.like_url),
        )
        if on
    )
    return f"{tok.i:>3} {tok.text!r} idx={tok.idx} shape={tok.shape_} {flags or '-'}"


def analyse(copies):
    """Tokenise `copies` joined copies of SOURCE and audit the result against plain regex.

    Every check reports the residual it measured rather than a bare pass, so a
    disagreement shows up as a number on screen instead of as a missing exception. The
    regex reference deliberately knows nothing about spaCy: it is `re.finditer` over the
    same string, which is the only independent answer available offline.

    The caller holds `lock` around the whole call: every attribute read below goes through
    the shared Vocab that a concurrent pass would be growing.
    """
    text = " ".join([SOURCE] * copies)
    start = time.perf_counter()
    for _ in range(REPEATS):
        doc = nlp(text)
    ms = (time.perf_counter() - start) / REPEATS * 1000

    rebuilt = "".join(tok.text_with_ws for tok in doc)
    token_residual = residual(rebuilt, text)
    sentences = list(doc.sents)
    sentence_residual = residual("".join(s.text_with_ws for s in sentences), text)
    ruled = sorted((e.start_char, e.end_char, e.label_) for e in doc.ents)
    expected = sorted(
        (m.start(), m.end(), label)
        for phrase, label in PHRASES.items()
        for m in re.finditer(re.escape(phrase), text)
    )
    misplaced = [e for e in doc.ents if text[e.start_char : e.end_char] not in PHRASES]
    lowered = lower_matcher(doc)

    checks = [
        (
            "Reconstruction",
            token_residual == 0,
            f"{len(rebuilt)} chars rebuilt from text_with_ws, residual {token_residual}",
        ),
        (
            "Sentence partition",
            sentence_residual == 0,
            f"{len(sentences)} sentences, residual {sentence_residual}",
        ),
        (
            "Offset round trip",
            not misplaced,
            f"{len(doc.ents)} spans re-sliced to their pattern, {len(misplaced)} wrong",
        ),
        (
            "EntityRuler vs re.finditer",
            ruled == expected,
            f"{len(ruled)} spaCy spans against {len(expected)} regex spans",
        ),
        (
            "PhraseMatcher(attr='LOWER')",
            len(lowered) == len(expected),
            f"{len(lowered)} of {len(expected)} — 'corp.' tokenises unlike 'Corp.'",
        ),
    ]
    first = doc[0]
    return {
        "checks": checks,
        "stats": (
            f"{len(text):,} chars, {len(doc):,} tokens, {ms:.2f} ms/doc over {REPEATS} runs, "
            f"doc.mem.size {doc.mem.size:,} bytes"
        ),
        "statistical": (
            f"first token {first.text!r}: pos_={first.pos_!r} tag_={first.tag_!r} "
            f"lemma_={first.lemma_!r} dep_={first.dep_!r}"
        ),
        "sentences": [sent.text for sent in sentences[:3]],
        "entities": [
            f"{e.label_} {e.text!r} [{e.start_char}:{e.end_char}]" for e in doc.ents[:6]
        ],
        "tokens": [token_line(tok) for tok in doc[:24]],
        "n_entities": len(doc.ents),
        "n_tokens": len(doc),
    }


def main(page: ft.Page):
    """One screen: a model-free pipeline auditing itself over a document you can scale.

    The slider decides how many copies of the sample document to concatenate, so the
    per-document cost and spaCy's own memory pool are read across a range rather than at
    one point. The header says what is loaded against what merely exists.
    """

    def render(result):
        """Move one analyse() result onto the controls, without updating the page itself.

        The caller owns the update, because this runs on a worker thread where Flet's
        auto-update does not reach.
        """
        checks.controls = [
            ft.Row(
                controls=[
                    ft.Text(
                        "AGREE" if ok else "DISAGREE",
                        color=ft.Colors.GREEN if ok else ft.Colors.ORANGE,
                        weight=ft.FontWeight.BOLD,
                        size=12,
                        width=88,
                    ),
                    ft.Text(f"{name} — {detail}", size=12, expand=True),
                ]
            )
            for name, ok, detail in result["checks"]
        ]
        stats.value = result["stats"]
        statistical.value = result["statistical"]
        sentences.value = "\n".join(f"· {s}" for s in result["sentences"])
        entities.value = "\n".join(result["entities"]) + (
            f"\n… {result['n_entities']} in total" if result["n_entities"] > 6 else ""
        )
        tokens.value = "\n".join(result["tokens"]) + (
            f"\n… {result['n_tokens']} in total" if result["n_tokens"] > 24 else ""
        )

    def recompute():
        """Re-run the analysis off the UI thread and redraw.

        `lock` spans analyse *and* render because the pool overlaps two slider releases
        and both the Vocab and these controls are shared. page.run_thread also never
        retrieves the worker's future, so an exception here would vanish silently — hence
        the broad guard, which also covers the ValueError subclasses spaCy raises for its
        own error codes.
        """
        try:
            with lock:
                render(analyse(int(copies.value)))
        except Exception as exc:
            stats.value = f"{type(exc).__name__}: {exc}"
        page.update()

    def rerun():
        """Slider release: recomputing on every drag frame would be far too much work."""
        page.run_thread(recompute)

    page.appbar = ft.AppBar(title=ft.Text("spaCy without a model"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                expand=True,
                controls=[
                    ft.Text(
                        f"spacy {spacy.__version__} · blank('en') · "
                        f"loaded {nlp.pipe_names} of "
                        f"{len(registry.factories.get_all())} registered factories",
                        size=12,
                    ),
                    ft.Text(
                        "No model, no download, no data file — the rest need one.",
                        size=12,
                        italic=True,
                    ),
                    ft.Divider(),
                    checks := ft.Column(spacing=2),
                    stats := ft.Text(size=12, selectable=True),
                    ft.Divider(),
                    ft.Text("Statistical attributes come back empty", size=12),
                    statistical := ft.Text(size=11, selectable=True),
                    ft.Divider(),
                    copies := ft.Slider(
                        min=1,
                        max=64,
                        divisions=63,
                        value=1,
                        label="{value} copies",
                        on_change_end=rerun,
                    ),
                    ft.Text("Sentences", weight=ft.FontWeight.BOLD, size=12),
                    sentences := ft.Text(size=11, selectable=True),
                    ft.Text("Entities", weight=ft.FontWeight.BOLD, size=12),
                    entities := ft.Text(size=11, selectable=True),
                    ft.Text("Tokens", weight=ft.FontWeight.BOLD, size=12),
                    tokens := ft.Text(size=11, selectable=True),
                ],
            ),
        )
    )

    page.run_thread(recompute)


if __name__ == "__main__":
    ft.run(main)

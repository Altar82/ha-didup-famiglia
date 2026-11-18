"""Trasforma la dashboard grezza di Argo in strutture semplici.

Il formato non è documentato: ogni campo è letto in modo difensivo e con
nomi alternativi, così un cambio minore lato Argo non rompe tutto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any


def _first(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _date(v: Any) -> date | None:
    if not v:
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    try:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
        if m:
            return date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        return None
    return None


def _items(dash: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    """Lista di elementi, escludendo quelli marcati come cancellati (operazione D)."""
    for k in keys:
        v = dash.get(k)
        if isinstance(v, list):
            return [i for i in v if isinstance(i, dict) and str(i.get("operazione", "I")).upper() != "D"]
    return []


def _teacher(i: dict[str, Any]) -> str | None:
    t = _first(i, "docente", "desDocente")
    if isinstance(t, dict):
        t = " ".join(x for x in (t.get("nome"), t.get("cognome")) if x) or t.get("nominativo")
    if isinstance(t, str):
        return t.strip("() ").strip() or None
    return None


def _subject(i: dict[str, Any]) -> str | None:
    m = _first(i, "desMateria", "materia", "materiaLight")
    if isinstance(m, dict):
        m = _first(m, "descrizione", "desMateria", "scuMateriaPK")
    return str(m).strip() if m else None


GRADE_FRACTIONS = {"½": 0.5, "+": 0.25, "-": -0.25}


def grade_value(raw: Any) -> float | None:
    """'7½' -> 7.5, '6+' -> 6.25, '8-' -> 7.75, '6/7' -> 6.5."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace(",", ".")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", s)
    if m:
        return (float(m[1]) + float(m[2])) / 2
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([½+\-]{0,2})", s)
    if not m:
        return None
    v = float(m[1])
    for ch in m[2]:
        v += GRADE_FRACTIONS[ch]
    return v


@dataclass
class Grade:
    pk: str
    date: date | None
    subject: str | None
    display: str | None
    value: float | None
    kind: str | None
    description: str | None
    comment: str | None
    teacher: str | None
    counts_in_average: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "data": self.date.isoformat() if self.date else None,
            "materia": self.subject,
            "voto": self.display,
            "valore": self.value,
            "tipo": self.kind,
            "descrizione": self.description,
            "commento": self.comment,
            "docente": self.teacher,
        }


KIND = {"S": "scritto", "O": "orale", "P": "pratico", "N": "unico"}


def parse_grades(dash: dict[str, Any]) -> list[Grade]:
    out: list[Grade] = []
    for i in _items(dash, "voti", "votiGiornalieri"):
        display = _first(i, "codVoto", "voto", "descrizioneVoto")
        value = _first(i, "valore")
        try:
            value = float(value) if value is not None else None
        except (TypeError, ValueError):
            value = None
        # valore 0/assente: lo ricaviamo dal voto testuale (es. "6-"); i giudizi restano None
        if not value:
            value = grade_value(display)
        kind = _first(i, "codVotoPratico", "tipo")
        out.append(
            Grade(
                pk=str(_first(i, "pk", "prgVoto", default=id(i))),
                date=_date(_first(i, "datGiorno", "data", "datEvento")),
                subject=_subject(i),
                display=str(display) if display is not None else None,
                value=value,
                kind=KIND.get(str(kind).upper(), kind) if kind else None,
                description=_first(i, "descrizioneProva", "desProva"),
                comment=_first(i, "desCommento", "commento"),
                teacher=_teacher(i),
                counts_in_average=str(_first(i, "numMedia", default="1")) not in ("0", "False", "false"),
            )
        )
    out.sort(key=lambda g: (g.date or date.min, g.pk), reverse=True)
    return out


def averages(dash: dict[str, Any], grades: list[Grade]) -> tuple[float | None, dict[str, float]]:
    """Media generale (quella di Argo se presente) e medie per materia calcolate."""
    per_subject: dict[str, list[float]] = {}
    for g in grades:
        if g.value is not None and g.counts_in_average and g.subject:
            per_subject.setdefault(g.subject, []).append(g.value)
    subj = {k: round(sum(v) / len(v), 2) for k, v in sorted(per_subject.items())}
    general = dash.get("mediaGenerale")
    try:
        general = round(float(general), 2) if general not in (None, "") else None
    except (TypeError, ValueError):
        general = None
    if general is None:
        allv = [v for vs in per_subject.values() for v in vs]
        general = round(sum(allv) / len(allv), 2) if allv else None
    return general, subj


@dataclass
class Homework:
    pk: str
    due: date | None
    assigned: date | None
    subject: str | None
    text: str
    teacher: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "consegna": self.due.isoformat() if self.due else None,
            "assegnato": self.assigned.isoformat() if self.assigned else None,
            "materia": self.subject,
            "compito": self.text,
            "docente": self.teacher,
        }


def parse_homework(dash: dict[str, Any]) -> list[Homework]:
    out: list[Homework] = []
    seen: set[tuple] = set()
    for lez in _items(dash, "registro"):
        assigned = _date(_first(lez, "datGiorno", "datEvento"))
        subj = _subject(lez)
        teacher = _teacher(lez)
        compiti = lez.get("compiti") or []
        if isinstance(compiti, dict):
            compiti = [compiti]
        for n, c in enumerate(compiti):
            if not isinstance(c, dict):
                continue
            text = str(_first(c, "compito", "desCompito", default="")).strip()
            if not text:
                continue
            due = _date(_first(c, "dataConsegna", "datConsegna")) or assigned
            key = (due, subj, text)
            if key in seen:
                continue
            seen.add(key)
            out.append(Homework(f"{_first(lez, 'pk', default='x')}_{n}", due, assigned, subj, text, teacher))
    out.sort(key=lambda h: (h.due or date.max, h.subject or ""))
    return out


@dataclass
class Reminder:
    pk: str
    date: date | None
    text: str
    teacher: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "data": self.date.isoformat() if self.date else None,
            "promemoria": self.text,
            "docente": self.teacher,
        }


def parse_reminders(dash: dict[str, Any]) -> list[Reminder]:
    out = []
    for i in _items(dash, "promemoria"):
        text = str(_first(i, "desAnnotazioni", "annotazioni", "descrizione", default="")).strip()
        if text:
            out.append(Reminder(str(_first(i, "pk", default=id(i))), _date(_first(i, "datGiorno", "data")), text, _teacher(i)))
    out.sort(key=lambda r: r.date or date.max)
    return out


@dataclass
class Absence:
    pk: str
    date: date | None
    kind: str  # assenza | ritardo | uscita | altro
    description: str | None
    to_justify: bool
    justified: bool
    teacher: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "data": self.date.isoformat() if self.date else None,
            "tipo": self.kind,
            "descrizione": self.description,
            "da_giustificare": self.to_justify,
            "giustificata": self.justified,
        }


ABSENCE_CODES = {"A": "assenza", "I": "ritardo", "U": "uscita"}


def _truthy(v: Any) -> bool:
    return v is True or str(v).strip().upper() in ("S", "SI", "TRUE", "1", "Y")


def parse_absences(dash: dict[str, Any]) -> list[Absence]:
    out = []
    for i in _items(dash, "appello", "assenze"):
        code = str(_first(i, "codEvento", "tipo", default="")).upper()[:1]
        kind = ABSENCE_CODES.get(code, "altro")
        justified = _truthy(_first(i, "giustificata", "flgGiustificata", default=False)) or bool(
            _first(i, "dataGiustificazione", "datGiustificazione")
        )
        to_justify = _truthy(_first(i, "daGiustificare", default=False)) and not justified
        out.append(
            Absence(
                pk=str(_first(i, "pk", default=id(i))),
                date=_date(_first(i, "data", "datAssenza", "datGiorno", "datEvento")),
                kind=kind,
                description=_first(i, "descrizione", "nota", "commentoGiustificazione"),
                to_justify=to_justify,
                justified=justified,
                teacher=_teacher(i),
            )
        )
    out.sort(key=lambda a: a.date or date.min, reverse=True)
    return out


@dataclass
class Note:
    pk: str
    date: date | None
    text: str
    category: str | None
    teacher: str | None
    seen: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "data": self.date.isoformat() if self.date else None,
            "nota": self.text,
            "categoria": self.category,
            "docente": self.teacher,
            "vista": self.seen,
        }


def parse_notes(dash: dict[str, Any]) -> list[Note]:
    out = []
    for i in _items(dash, "noteDisciplinari", "note"):
        if _truthy(_first(i, "isAnnullata", "flgAnnullata", default=False)):
            continue
        out.append(
            Note(
                pk=str(_first(i, "pk", default=id(i))),
                date=_date(_first(i, "datNota", "data", "datEvento")),
                text=str(_first(i, "desNota", "desDescrizione", "nota", "descrizione", default="")).strip(),
                category=_first(i, "categoria", "desTipologia"),
                teacher=_teacher(i),
                seen=_truthy(_first(i, "flgVisto", "isVisto", "visto", "isVisualizzata", default=False)),
            )
        )
    out.sort(key=lambda n: n.date or date.min, reverse=True)
    return out


@dataclass
class Notice:
    pk: str
    date: date | None
    title: str
    category: str | None
    author: str | None
    url: str | None
    needs_ack: bool
    acked: bool
    attachments: list[str] = field(default_factory=list)
    attachment_ids: list[str] = field(default_factory=list)
    # (id, nome file) di ogni allegato scaricabile
    files: list[tuple[str, str]] = field(default_factory=list)

    @property
    def unread(self) -> bool:
        return self.needs_ack and not self.acked

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.pk,
            "data": self.date.isoformat() if self.date else None,
            "titolo": self.title,
            "categoria": self.category,
            "autore": self.author,
            "presa_visione_richiesta": self.needs_ack,
            "presa_visione": self.acked,
            "allegati": self.attachments,
            "url": self.url,
        }


def parse_notices(dash: dict[str, Any]) -> list[Notice]:
    out = []
    for i in _items(dash, "bacheca"):
        att, att_ids, files = [], [], []
        for a in i.get("listaAllegati") or []:
            if isinstance(a, dict):
                name = _first(a, "nomeFile", "desFile", "descrizione", "descrizioneFile")
                if name:
                    att.append(str(name))
                if a.get("pk"):
                    att_ids.append(str(a["pk"]))
                    files.append((str(a["pk"]), str(name or a["pk"])))
        acked = _truthy(_first(i, "isPresaVisione", "presaVisione", default=False)) or bool(
            i.get("dataConfermaPresaVisione")
        )
        out.append(
            Notice(
                pk=str(_first(i, "pk", default=id(i))),
                date=_date(_first(i, "data", "datGiorno", "datEvento")),
                title=str(_first(i, "messaggio", "titolo", "desMessaggio", default="")).strip(),
                category=_first(i, "categoria"),
                author=_first(i, "autore"),
                url=_first(i, "url"),
                needs_ack=_truthy(_first(i, "pvRichiesta", default=False)),
                acked=acked,
                attachments=att,
                attachment_ids=att_ids,
                files=files,
            )
        )
    out.sort(key=lambda n: n.date or date.min, reverse=True)
    return out


@dataclass
class StudentData:
    grades: list[Grade]
    average: float | None
    subject_averages: dict[str, float]
    homework: list[Homework]
    reminders: list[Reminder]
    absences: list[Absence]
    notes: list[Note]
    notices: list[Notice]


def parse_dashboard(dash: dict[str, Any]) -> StudentData:
    grades = parse_grades(dash)
    avg, subj = averages(dash, grades)
    return StudentData(
        grades=grades,
        average=avg,
        subject_averages=subj,
        homework=parse_homework(dash),
        reminders=parse_reminders(dash),
        absences=parse_absences(dash),
        notes=parse_notes(dash),
        notices=parse_notices(dash),
    )

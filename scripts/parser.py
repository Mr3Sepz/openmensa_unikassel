#!/usr/bin/env python3
# scripts/parser.py
# Erzeugt ein OpenMensa v2 XML feed für Zentralmensa Arnold-Bode-Straße

import re, sys
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from pathlib import Path

URL = "https://www.studierendenwerk-kassel.de/speiseplaene/zentralmensa-arnold-bode-strasse"
NAMESPACE = "http://openmensa.org/open-mensa-v2"
ET.register_namespace("", NAMESPACE)

def fetch_html(url=URL, timeout=15):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text

def extract_year_from_text(text):
    m = re.search(r'(\d{1,2}\.\d{1,2}\.\d{4})\s*-\s*(\d{1,2}\.\d{1,2}\.\d{4})', text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%d.%m.%Y").year
        except:
            pass
    return datetime.now().year

def normalize_price(s):
    if not s:
        return None
    s = s.strip().replace("€", "").replace(" ", "")
    s = s.replace(",", ".")
    s = re.sub(r'[^\d\.].*$', '', s)
    try:
        return float(s)
    except:
        return None

def parse_text_blocks(text):
    year = extract_year_from_text(text)
    pattern = re.compile(r'####\s*([A-Za-zÄÖÜäöüß]+),\s*(\d{1,2}\.\d{1,2}\.)', re.MULTILINE)
    matches = list(pattern.finditer(text))
    days = []
    for i, m in enumerate(matches):
        weekday = m.group(1).strip()
        date_part = m.group(2).strip() + str(year)
        try:
            date_iso = datetime.strptime(date_part, "%d.%m.%Y").date().isoformat()
        except:
            date_iso = None
        start = m.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        block = text[start:end].strip()
        entries = re.split(r'\n\s*\*\s*#####\s*', block)
        meals = []
        for ent in entries:
            ent = ent.strip()
            if not ent:
                continue
            header_match = re.match(r'^([^\n]+)\n+', ent)
            if not header_match:
                continue
            cat_raw = header_match.group(1).strip()
            body = ent[header_match.end():].strip()
            if re.match(r'(?i)essen\s*\d+', cat_raw):
                cat = "Hauptgericht"
            else:
                cat = cat_raw
            lines = [ln.strip() for ln in body.splitlines() if ln.strip()!='']
            if not lines:
                continue
            name = lines[0]
            price_line = None
            for ln in lines[1:6]:
                if re.search(r'\d+[,\.]\d+\s*€', ln):
                    price_line = ln
                    break
            labels = re.findall(r'\(([^)]+)\)', cat_raw + " " + body)
            notes = []
            allergen_codes = []
            for l in labels:
                if re.search(r'[A-Za-zÄÖÜäöüß]', l):
                    for part in re.split(r'[\/,]', l):
                        p = part.strip()
                        if p:
                            notes.append(p)
                else:
                    for code in re.split(r'[\/,]', l):
                        c = code.strip()
                        if c:
                            allergen_codes.append(c)
            for ln in lines[1:]:
                if ln == price_line:
                    continue
                if re.match(r'^[\d,\s\/\(\)]+$', ln):
                    continue
                if ln not in notes:
                    notes.append(ln)
            student_p = employee_p = others_p = None
            if price_line:
                parts = [p.strip() for p in re.split(r'\/', price_line) if p.strip()!='']
                if len(parts) >= 1:
                    student_p = normalize_price(parts[0])
                if len(parts) >= 2:
                    employee_p = normalize_price(parts[1])
                if len(parts) >= 3:
                    others_p = normalize_price(parts[2])
            meals.append({
                "category": cat,
                "name": name,
                "notes": notes,
                "allergens": allergen_codes,
                "prices": {"students": student_p, "employees": employee_p, "others": others_p}
            })
        days.append({"date": date_iso, "weekday": weekday, "meals": meals})
    return days

def build_openmensa_xml(canteen_name, days):
    root = ET.Element(ET.QName(NAMESPACE, "openmensa"), {"version": "2.1"})
    canteen = ET.SubElement(root, ET.QName(NAMESPACE, "canteen"))
    name_el = ET.SubElement(canteen, ET.QName(NAMESPACE, "name"))
    name_el.text = canteen_name
    for d in days:
        if not d["date"]:
            continue
        day_el = ET.SubElement(canteen, ET.QName(NAMESPACE, "day"), {"date": d["date"]})
        groups = {}
        for m in d["meals"]:
            groups.setdefault(m["category"], []).append(m)
        for cat_name, meals in groups.items():
            cat_el = ET.SubElement(day_el, ET.QName(NAMESPACE, "category"), {"name": cat_name})
            for m in meals:
                meal_el = ET.SubElement(cat_el, ET.QName(NAMESPACE, "meal"))
                n = ET.SubElement(meal_el, ET.QName(NAMESPACE, "name"))
                n.text = m["name"]
                for note in m["notes"]:
                    note_el = ET.SubElement(meal_el, ET.QName(NAMESPACE, "note"))
                    note_el.text = note
                for code in m["allergens"]:
                    note_el = ET.SubElement(meal_el, ET.QName(NAMESPACE, "note"))
                    note_el.text = "Allergene: " + code
                for role, value in m["prices"].items():
                    if value is None:
                        continue
                    price_el = ET.SubElement(meal_el, ET.QName(NAMESPACE, "price"), {"role": role})
                    price_el.text = "{:.2f}".format(value)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode('utf-8')

def main():
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        html = fetch_html(URL)
    except Exception as e:
        print("Fehler beim Abruf:", e, file=sys.stderr)
        sys.exit(2)
    # try to get structured text (we parse the plain text content)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    days = parse_text_blocks(text)
    if len(days) == 0:
        print("Keine Tage geparst!", file=sys.stderr)
        sys.exit(3)
    xml = build_openmensa_xml("Zentralmensa Arnold-Bode-Straße (Studierendenwerk Kassel)", days)
    out_file = out_dir / "feed.xml"
    out_file.write_text(xml, encoding="utf-8")
    print("Feed geschrieben:", out_file)
    # simple sanity check: we expect at least 4 days
    if sum(1 for d in days if d["date"]) < 4:
        print("Warnung: weniger als 4 Tage geparst.", file=sys.stderr)
        sys.exit(4)
    sys.exit(0)

if __name__ == "__main__":
    main()

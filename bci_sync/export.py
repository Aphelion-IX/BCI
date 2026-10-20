"""Export BCI records to XML."""
import re
import xml.etree.ElementTree as ET

_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def to_xml(rows, root="projects", item="project"):
    """Serialise a list of dicts to an XML string; None values become empty elements."""
    top = ET.Element(root, count=str(len(rows)))
    for row in rows:
        el = ET.SubElement(top, item)
        for key, value in row.items():
            ET.SubElement(el, key.lower()).text = "" if value is None else _INVALID_XML.sub("", str(value))
    ET.indent(top)
    return ET.tostring(top, encoding="unicode", xml_declaration=False)


def write_xml(path, rows, root="projects", item="project"):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n' + to_xml(rows, root, item) + "\n")

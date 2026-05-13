from dateutil.relativedelta import relativedelta
from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _get_proforma_sections(self):
        """Agrupa las líneas de la orden por sección para el reporte pro-forma.
        Retorna una lista de dicts con: name, lines, subtotal, taxes (lista), total.
        """
        sections = []
        current = {"name": None, "lines": [], "subtotal": 0.0, "taxes": {}}

        for line in self._get_order_lines_to_report():
            if line.display_type == "line_section":
                if current["lines"]:
                    sections.append(self._finalize_proforma_section(current))
                current = {
                    "name": line.name,
                    "lines": [],
                    "subtotal": 0.0,
                    "taxes": {},
                }
            else:
                current["lines"].append(line)
                if not line.display_type:
                    current["subtotal"] += line.price_subtotal
                    for tax in line.tax_id:
                        k = tax.id
                        if k not in current["taxes"]:
                            current["taxes"][k] = {
                                "label": tax.invoice_label or tax.name,
                                "rate": tax.amount,
                                "base": 0.0,
                                "amount": 0.0,
                            }
                        current["taxes"][k]["base"] += line.price_subtotal
                        current["taxes"][k]["amount"] += (
                            line.price_subtotal * tax.amount / 100.0
                        )

        if current["lines"]:
            sections.append(self._finalize_proforma_section(current))
        return sections

    def _finalize_proforma_section(self, section):
        tax_list = sorted(section["taxes"].values(), key=lambda x: x["rate"])
        total = section["subtotal"] + sum(t["amount"] for t in tax_list)
        return {
            "name": section["name"],
            "lines": section["lines"],
            "subtotal": section["subtotal"],
            "taxes": tax_list,
            "total": total,
        }

    def _get_proforma_payment_lines(self):
        """Calcula el cronograma de pagos desde el término de pago de la orden."""
        if not self.payment_term_id:
            return []

        date_ref = (
            self.date_order.date() if self.date_order else fields.Date.today()
        )
        total = self.amount_total
        lines = []
        cumulative_pct = 0.0

        for pt_line in self.payment_term_id.line_ids.sorted("sequence"):
            if pt_line.value == "percent":
                pct = pt_line.value_amount
                amount = total * pct / 100.0
                cumulative_pct += pct
            elif pt_line.value == "balance":
                pct = 100.0 - cumulative_pct
                amount = total * pct / 100.0
            else:
                amount = pt_line.value_amount
                pct = (amount / total * 100.0) if total else 0.0

            due_date = date_ref + relativedelta(days=pt_line.nb_days)
            lines.append({"date": due_date, "percent": pct, "amount": amount})

        return lines

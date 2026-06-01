from dateutil.relativedelta import relativedelta
from odoo import Command, api, exceptions, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    proforma_type = fields.Selection(
        [
            ("sale", "Venta"),
            ("national", "Venta Nacional"),
            ("customs_zone", "Venta en Zona Primaria"),
        ],
        string="Tipo de Venta",
        default="sale",
        required=True,
    )
    proforma_name = fields.Char(string="N° Proforma", copy=False, readonly=True)
    delivery_period_days = fields.Integer(string="Período de Entrega (días)")
    custom_payment_line_ids = fields.One2many(
        "aerotec.sale.payment.line", "order_id", string="Plan de pagos"
    )
    aerotec_auto_payment_term_id = fields.Many2one(
        "account.payment.term",
        string="Término auto-generado",
        copy=False,
    )
    custom_payment_pct_total = fields.Float(
        compute="_compute_custom_payment_pct_total",
        string="Total %",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.proforma_type in ("national", "customs_zone"):
                record.proforma_name = self.env["ir.sequence"].next_by_code(
                    "aerotec.proforma"
                )
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get("proforma_type") in ("national", "customs_zone"):
            for record in self:
                if not record.proforma_name:
                    record.proforma_name = self.env["ir.sequence"].next_by_code(
                        "aerotec.proforma"
                    )
        if "custom_payment_line_ids" in vals:
            for record in self:
                if abs(record.custom_payment_pct_total - 100.0) < 0.01:
                    record._sync_custom_payment_term()
        return res

    def action_confirm(self):
        for order in self:
            if order.custom_payment_line_ids:
                total = sum(order.custom_payment_line_ids.mapped("percent"))
                if abs(total - 100.0) > 0.01:
                    raise exceptions.UserError(
                        f"El plan de pagos de {order.name} no suma 100% "
                        f"(actual: {total:.2f}%). Corrija los porcentajes antes de confirmar."
                    )
                if not order.aerotec_auto_payment_term_id:
                    order._sync_custom_payment_term()
        return super().action_confirm()

    def action_cancel(self):
        res = super().action_cancel()
        for order in self:
            if order.aerotec_auto_payment_term_id:
                order.aerotec_auto_payment_term_id.action_archive()
        return res

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        if self.custom_payment_line_ids:
            lines_text = "\n".join(
                f"• {line.label}: {line.percent:.0f}% — {line.nb_days} días desde la factura"
                for line in self.custom_payment_line_ids.sorted("sequence")
            )
            vals["invoice_line_ids"].append(
                Command.create({
                    "display_type": "line_note",
                    "name": f"Plan de pagos acordado:\n{lines_text}",
                    "sequence": 9999,
                })
            )
        return vals

    @api.depends("custom_payment_line_ids.percent")
    def _compute_custom_payment_pct_total(self):
        for order in self:
            order.custom_payment_pct_total = sum(
                order.custom_payment_line_ids.mapped("percent")
            )

    def _sync_custom_payment_term(self):
        """Crea o actualiza el account.payment.term privado vinculado a esta orden."""
        self.ensure_one()
        lines = self.custom_payment_line_ids.sorted("sequence")
        term_line_vals = [
            Command.create({
                "value": "percent",
                "value_amount": line.percent,
                "nb_days": line.nb_days,
                "delay_type": "days_after",
            })
            for line in lines
        ]
        if self.aerotec_auto_payment_term_id:
            self.aerotec_auto_payment_term_id.line_ids.unlink()
            self.aerotec_auto_payment_term_id.write({"line_ids": term_line_vals})
        else:
            term = self.env["account.payment.term"].create({
                "name": f"Negociado — {self.name}",
                "line_ids": term_line_vals,
            })
            self.aerotec_auto_payment_term_id = term
        self.payment_term_id = self.aerotec_auto_payment_term_id

    def _get_proforma_sections(self):
        """Agrupa las líneas de la orden por sección para el reporte pro-forma.
        Retorna una lista de dicts con: name, lines, subtotal, taxes (lista), total.
        """
        sections = []
        current = {"name": None, "lines": [], "subtotal": 0.0, "gross_subtotal": 0.0, "taxes": {}}

        for line in self._get_order_lines_to_report():
            if line.display_type == "line_section":
                if current["lines"]:
                    sections.append(self._finalize_proforma_section(current))
                current = {
                    "name": line.name,
                    "lines": [],
                    "subtotal": 0.0,
                    "gross_subtotal": 0.0,
                    "taxes": {},
                }
            else:
                current["lines"].append(line)
                if not line.display_type:
                    current["subtotal"] += line.price_subtotal
                    current["gross_subtotal"] += line.price_unit * line.product_uom_qty
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

    def _get_proforma_opcionales_aggregate(self):
        """Combina todas las secciones opcionales (índice 1 en adelante) en una
        única estructura con subtotales e impuestos agregados."""
        all_sections = self._get_proforma_sections()
        if len(all_sections) <= 1:
            return None
        opcionales = all_sections[1:]
        agg_subtotal = sum(s["subtotal"] for s in opcionales)
        agg_gross_subtotal = sum(s["gross_subtotal"] for s in opcionales)
        agg_taxes = {}
        for s in opcionales:
            for tax in s["taxes"]:
                k = tax["rate"]
                if k not in agg_taxes:
                    agg_taxes[k] = {
                        "label": tax["label"],
                        "rate": tax["rate"],
                        "base": 0.0,
                        "amount": 0.0,
                    }
                agg_taxes[k]["base"] += tax["base"]
                agg_taxes[k]["amount"] += tax["amount"]
        agg_tax_list = sorted(agg_taxes.values(), key=lambda x: x["rate"])
        agg_total = agg_subtotal + sum(t["amount"] for t in agg_tax_list)
        return {
            "sections": opcionales,
            "subtotal": agg_subtotal,
            "gross_subtotal": agg_gross_subtotal,
            "discount_total": agg_gross_subtotal - agg_subtotal,
            "taxes": agg_tax_list,
            "total": agg_total,
        }

    def _finalize_proforma_section(self, section):
        tax_list = sorted(section["taxes"].values(), key=lambda x: x["rate"])
        total = section["subtotal"] + sum(t["amount"] for t in tax_list)
        gross_subtotal = section["gross_subtotal"]
        return {
            "name": section["name"],
            "lines": section["lines"],
            "subtotal": section["subtotal"],
            "gross_subtotal": gross_subtotal,
            "discount_total": gross_subtotal - section["subtotal"],
            "taxes": tax_list,
            "total": total,
        }

    def _get_proforma_payment_lines(self):
        """Calcula el cronograma de pagos para la pro-forma.
        Usa las líneas custom si están definidas; si no, cae al payment_term_id estándar.
        """
        date_ref = self.date_order.date() if self.date_order else fields.Date.today()
        total = self.amount_total

        if self.custom_payment_line_ids:
            return [
                {
                    "date": date_ref + relativedelta(days=line.nb_days),
                    "percent": line.percent,
                    "amount": total * line.percent / 100.0,
                    "label": line.label,
                }
                for line in self.custom_payment_line_ids.sorted("sequence")
            ]

        if not self.payment_term_id:
            return []

        lines = []
        cumulative_pct = 0.0
        for pt_line in self.payment_term_id.line_ids.sorted("nb_days"):
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

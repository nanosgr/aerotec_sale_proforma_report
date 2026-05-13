from odoo import models
from odoo.tools.misc import formatLang


class ReportAerotecProforma(models.AbstractModel):
    # El nombre DEBE seguir el patrón report.<module>.<template_xml_id>
    _name = "report.aerotec_sale_proforma_report.aerotec_proforma"
    _description = "Aerotec Pro-Forma Report"

    def _get_report_values(self, docids, data=None):
        docs = self.env["sale.order"].browse(docids)
        return {
            "doc_ids": docids,
            "doc_model": "sale.order",
            "docs": docs,
            "format_amount": lambda amount, currency, **kwargs: formatLang(
                self.env, amount, currency_obj=currency
            ),
        }

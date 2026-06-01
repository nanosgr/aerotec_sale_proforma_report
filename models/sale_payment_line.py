from odoo import api, fields, models


class AerotecSalePaymentLine(models.Model):
    _name = "aerotec.sale.payment.line"
    _description = "Línea de plan de pagos de venta"
    _order = "sequence, id"

    order_id = fields.Many2one(
        "sale.order", ondelete="cascade", required=True, index=True
    )
    sequence = fields.Integer(default=10)
    label = fields.Char(string="Concepto", required=True)
    percent = fields.Float(string="%", digits=(5, 2), required=True)
    nb_days = fields.Integer(string="Días desde factura", default=0)
    amount = fields.Float(
        string="Importe estimado",
        compute="_compute_amount",
        digits="Product Price",
    )

    @api.depends("percent", "order_id.amount_total")
    def _compute_amount(self):
        for line in self:
            line.amount = line.order_id.amount_total * line.percent / 100.0

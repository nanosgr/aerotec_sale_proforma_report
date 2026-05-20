from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    configuration = fields.Html(string="Configuration")

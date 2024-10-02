from datetime import datetime
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, SUPERUSER_ID, _
from odoo.osv import expression
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.tools.float_utils import float_compare
from odoo.exceptions import UserError, AccessError, ValidationError
from odoo.tools.misc import formatLang
from odoo.addons import decimal_precision as dp


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    requisition_number = fields.Char('PO Requisition')
    requisition_id = fields.Many2one('po.requisition', 'Requisition')


class Requisition(models.Model):
    _name = "po.requisition"
    _inherit = ['mail.thread']

    @api.model
    def _po_count(self):
        attach = self.env['purchase.order']
        for po in self:
            domain = [('requisition_id', '=', self.id)]
            attach_ids = attach.search(domain)
            po_count = len(attach_ids)
            po.po_count = po_count
        return True
    
    # @api.depends('order_line')
    # def _calc_po_total(self):
    #     for rec in self:
    #         for line in rec.order_line:
    #             rec.total += line.total

    name = fields.Char('PO Requisition', default='/')
    user = fields.Many2one('res.users', 'Approved By')
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse', required=True, default=1)
    po_count = fields.Integer('RFQs/POs', compute=_po_count)
    request_title = fields.Char(string="Request Title")
    total = fields.Float(string='Total',readonly=True, compute='_calc_all_totals', tracking=True)
    currency = fields.Many2one('res.currency')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    delivery_date = fields.Datetime(
        string='Delivery Date', required=True, index=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approve', 'Approved'),
        ('cancel', 'Cancelled')
    ], string='Status', readonly=True, index=True, copy=False, default='draft', track_visibility='always')
    partner_id = fields.Many2one('res.partner', string='Vendor',
                                 help="You can find a vendor by its Name, TIN, Email or Internal Reference.")
    order_line = fields.One2many('requisition.order.line', 'order_id', string='Order Lines', states={
                                 'cancel': [('readonly', True)], 'done': [('readonly', True)]}, copy=True, track_visibility='always')


    
    @api.depends('order_line.total')
    def _calc_all_totals(self):
        for rec in self:
            total = 0.0
            for line in rec.order_line:
                total += line.total
            rec.update({
                'total': total,
            })

    def action_approve_po_requisition(self):
        if self.order_line:
            for rec in self:
                
                unique_ids = []
                for line_item in self.order_line:
                    if not line_item.partner_id:
                        raise UserError(_('Please Add Vendor/Spplier'))
                    # if not (line_item.partner_id.id in unique_ids):
                    #     unique_ids.append(line_item.partner_id.id)
                for item in unique_ids:
                    records = self.env['requisition.order.line'].search([('partner_id', '=', item),('order_id','=',rec.id)])
                    po_data = {
                        'requisition_number': str(self.name),
                        'date_order': fields.datetime.now(),
                        'partner_id': item,
                        'requisition_id': self.id,
                        'currency_id': self.currency.id,
                    }
                    po_line_list = list()
                    for line in records:                        
                        po_line_list.append([0, False,
                            {
                                'name': line.product_id.product_tmpl_id.name + " "+line.name if  line.name else line.product_id.product_tmpl_id.name,
                                'product_id': line.product_id.id,
                                'product_qty': line.product_qty,
                                'product_uom': line.product_uom.id,
                                'date_planned': fields.datetime.now(),
                                'price_unit': line.price_unit,
                                # 'price_unit': line.price_unit,
                            }])

                    po_data['order_line'] = po_line_list

                    # create PO
                    po_env = self.env['purchase.order'].create(po_data)
                rec.write({
                    'state':'approve',
                    'user':self.env.uid,
                })
        return True

    def cancel(self):
        for rec in self:
            rec.state = 'cancel'


    # @api.model
    def unlink(self):
        for rec in self:
            if rec.state in ('approve','cancel'):
                raise UserError(_("You can only delet records in Draft State!"),_("Something is wrong!"),_("error"))               
        return super(Requisition, self).unlink()

    @api.model
    def create(self, values):
        
        record = super(Requisition, self).create(values)
        record.name = "REQ0"+str(record.id)

        return record


class RequisitionOrderLine(models.Model):
    _name = 'requisition.order.line'
    _description = 'Requisition Order Line'
    # _inherit = ['mail.thread',]

    @api.depends('product_qty','price_unit')
    def _calc_total(self):
        for rec in self:
            rec.total = rec.price_unit * rec.product_qty

    order_id = fields.Many2one(
        'po.requisition', string='Order Reference', index=True, required=True, ondelete='cascade')
    name = fields.Text(string='Description')
    product_id = fields.Many2one('product.product', string='Product', domain=[
                                 ('purchase_ok', '=', True)], change_default=True, required=True)
    product_qty = fields.Float(string='Quantity', digits=dp.get_precision(
        'Product Unit of Measure'), required=True)

    product_uom = fields.Many2one(
        'uom.uom', string='Product Unit of Measure', required=True, related="product_id.uom_po_id")
    price_unit = fields.Float(string='Price', digits=dp.get_precision(
        'Product Price'))
    total = fields.Float(string='Total', digits=dp.get_precision(
        'Product Price'), compute=_calc_total)
    partner_id = fields.Many2one('res.partner', string='Vendor/Supplier',
                                 help="You can find a vendor by its Name, TIN, Email or Internal Reference.")

    # amount_total = fields.Monetary(string='Total', store=True, readonly=True,
    #     compute='_compute_amount',
    #     inverse='_inverse_amount_total')

    # def _compute_amount(self):
    #     for order in self:
    #         total = 0.0
    #         for line in order.order_line:
    #             total += line.total
    #         order.amount_undiscounted = total
    

    @api.onchange('product_id')
    def _change_uom(self):
        for rec in self:
            if rec.product_id:
                # rec.product_uom = rec.product_id.uom_po_id.id
                rec.price_unit = rec.product_id.product_tmpl_id.standard_price

    @api.onchange('product_uom')
    def _change_uom2(self):
        for rec in self:
            if rec.product_uom.category_id.id != rec.product_id.uom_po_id.category_id.id:
                raise ValidationError("The Unit of Measure Selected does not belong to the same Category \
                     as the Product's purchase Unit of Measure")



# Odoo 12: Error, a partner cannot follow twice the same object
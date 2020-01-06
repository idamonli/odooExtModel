# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SALESTATE = [
    ('sign', '签约'),
    ('progress', '执行中'),
    ('finish', '完毕'),
    ('termination', '终止'),
]


class CrmSaleContract(models.Model):
    _name = 'crm.sale.contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = '订单合同'
    _rec_name = 'code'
    _order = 'id'

    def _default_currency(self):
        """
        获取当前公司默认币种
        :return:
        """
        return self.env.user.company_id.currency_id.id
    
    active = fields.Boolean(string=u'Active', default=True)
    company_id = fields.Many2one('res.company', '公司', default=lambda self: self.env.user.company_id, index=True)
    currency_id = fields.Many2one('res.currency', '币种', required=True, default=_default_currency)
    name = fields.Char(string="合同名称", required=True, track_visibility='onchange', index=True)
    code = fields.Char(string="合同编号", required=True, default='New', track_visibility='onchange', index=True)
    partner_id = fields.Many2one("res.partner", string="客户", required=True, index=True, track_visibility='onchange')
    contact_ids = fields.Many2many("crm.contact.users", string="联系人", domain="[('partner_id','=', partner_id)]")
    opportunity_ids = fields.Many2many("crm.sale.opportunity", string="关联机会", domain="[('partner_id','=', partner_id)]")
    order_ids = fields.Many2many("crm.sale.order", string="关联报价单", domain="[('partner_id','=', partner_id)]")
    signatory_id = fields.Many2one("res.users", string="签订人", default=lambda self: self.env.user.id)
    signing_date = fields.Date(string="签订日期", required=True, default=fields.Date.context_today)
    expiry_date = fields.Date(string="到期日期", default=fields.Date.context_today)
    principal_ids = fields.Many2many("res.users", "crm_sale_contract_and_res_users_rel", string="负责人", required=True)
    collaborator_ids = fields.Many2many("res.users", "crm_sale_contract_and_res_users_rel", string="协同人")
    state = fields.Selection(string="状态", selection=SALESTATE, default='sign', track_visibility='onchange')
    subtotal = fields.Monetary(string="合同金额", digits=(10, 2), store=True, compute='_amount_subtotal')
    note = fields.Text(string="备注")
    type_id = fields.Many2one(comodel_name="crm.contract.type", string="合同类型")
    payment_method_id = fields.Many2one(comodel_name="crm.contract.payment.method", string="付款方式")
    logistics_id = fields.Many2one(comodel_name="crm.contract.logistics.company", string="物流公司")
    logistics_code = fields.Char(string="物流单号")
    delivery_status = fields.Selection(string="发货状态", selection=[('00', '缺货'), ('01', '待发货'), ('02', '已发货')], default='01')
    line_ids = fields.One2many("crm.sale.contract.line", inverse_name="contract_id", string="合同明细")
    cashback_ids = fields.One2many("sale.contract.cashback.plan", inverse_name="contract_id", string="回款计划")
    attachment_number = fields.Integer(compute='_compute_attachment_number', string='附件')

    @api.model
    def create(self, values):
        values['code'] = self.env['ir.sequence'].sudo().next_by_code('crm.sale.contract.code')
        return super(CrmSaleContract, self).create(values)

    @api.onchange('line_ids')
    @api.depends('line_ids')
    def _amount_subtotal(self):
        """
        计算合计合同金额
        """
        for res in self:
            sum_amout = 0
            for line in res.line_ids:
                sum_amout += line.subtotal
            res.subtotal = sum_amout

    @api.onchange('order_ids')
    def _onchange_oeders(self):
        """
        将报价单中的明细行读取至合同明细
        """
        self.line_ids = False
        line_list = list()
        for order in self.order_ids:
            for line in order.line_ids:
                line_list.append({
                    'currency_id': self.currency_id.id,
                    'product_id': line.product_id.id,
                    'price': line.price,
                    'number': line.number,
                    'discount': line.discount,
                })
        self.line_ids = line_list

    @api.constrains('cashback_ids')
    def _constrains_cashback(self):
        """
        回款金额不能超过合同金额
        """
        cashback_amout = 0
        for res in self:
            for cashback in res.cashback_ids:
                cashback_amout += cashback.amount_received
            if cashback_amout > res.subtotal:
                raise UserError("回款计划金额总计不能超过合同的总计金额，请纠正！")

    def confirm_contract(self):
        """
        确认合同
        :return:
        """
        self.write({'state': 'progress'})

    def return_sign(self):
        """
        退回到签约状态
        :return:
        """
        self.write({'state': 'sign'})

    def contract_terminated(self):
        """
        已终止合同，修改状态
        :return:
        """
        self.write({'state': 'termination'})

    def contract_finish(self):
        """
        完成合同，修改状态
        :return:
        """
        self.write({'state': 'finish'})

    def create_invoice(self):
        """
        创建发票
        :return:
        """
        result = self.env.ref('odoo_crm.crm_sale_invoice_action').read()[0]
        result['context'] = {
            'default_partner_id': self.partner_id.id,
            'default_contract_id': self.id,
            'default_subtotal': self.subtotal,
            'default_invoice_look': self.partner_id.name,
        }
        res = self.env.ref('odoo_crm.crm_sale_invoice_view_form', False)
        result['views'] = [(res and res.id or False, 'form')]
        return result

    def action_sale_invoice(self):
        """
        跳转到销售发票
        :return:
        """
        result = self.env.ref('odoo_crm.crm_sale_invoice_action').read()[0]
        result['context'] = {
            'default_partner_id': self.partner_id.id,
            'default_contract_id': self.id,
            'default_subtotal': self.subtotal,
            'default_order_ids': [(6, 0, [self.id])]
        }
        result['domain'] = "[('partner_id', '=', %s)]" % (self.partner_id.id)
        return result

    def create_returns(self):
        """
        创建退货退款单
        :return:
        """
        result = self.env.ref('odoo_crm.crm_sale_order_return_action').read()[0]
        line_ids = list()
        for line in self.line_ids:
            line_ids.append({
                'currency_id': line.currency_id.id,
                'product_id': line.product_id.id,
                'price': line.price,
                'number': line.number,
                'discount': line.discount,
                'subtotal': line.subtotal,
            })
        result['context'] = {
            'default_name': "%s的退货退款单" % self.partner_id.name,
            'default_partner_id': self.partner_id.id,
            'default_contract_id': self.id,
            'default_subtotal': self.subtotal,
            'default_principal_ids': [(6, 0, [self.env.user.id])],
            'default_line_ids': line_ids,
        }
        res = self.env.ref('odoo_crm.crm_sale_order_return_form_view', False)
        result['views'] = [(res and res.id or False, 'form')]
        return result

    def action_sale_returns(self):
        """
        跳转到退货货款
        :return:
        """
        result = self.env.ref('odoo_crm.crm_sale_order_return_action').read()[0]
        line_ids = list()
        for line in self.line_ids:
            line_ids.append({
                'currency_id': line.currency_id.id,
                'product_id': line.product_id.id,
                'price': line.price,
                'number': line.number,
                'discount': line.discount,
                'subtotal': line.subtotal,
            })
        result['context'] = {
            'default_name': "%s的退货退款单" % self.partner_id.name,
            'default_partner_id': self.partner_id.id,
            'default_contract_id': self.id,
            'default_subtotal': self.subtotal,
            'default_principal_ids': [(6, 0, [self.env.user.id])],
            'default_line_ids': line_ids,
        }
        result['domain'] = "[('partner_id', '=', %s)]" % (self.partner_id.id)
        return result

    def attachment_image_preview(self):
        self.ensure_one()
        domain = [('res_model', '=', self._name), ('res_id', '=', self.id)]
        return {
            'domain': domain,
            'res_model': 'ir.attachment',
            'name': u'附件',
            'type': 'ir.actions.act_window',
            'view_id': False,
            'view_mode': 'kanban,tree,form',
            'view_type': 'form',
            'limit': 20,
            'context': "{'default_res_model': '%s','default_res_id': %d}" % (self._name, self.id)
        }

    def _compute_attachment_number(self):
        attachment_data = self.env['ir.attachment'].read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids)], ['res_id'], ['res_id'])
        attachment = dict((data['res_id'], data['res_id_count']) for data in attachment_data)
        for expense in self:
            expense.attachment_number = attachment.get(expense.id, 0)


class CrmSaleContractLine(models.Model):
    _name = 'crm.sale.contract.line'
    _description = '订单合同明细'
    _rec_name = 'contract_id'
    _order = 'id'

    def _default_currency(self):
        """
        获取当前公司默认币种
        :return:
        """
        return self.env.user.company_id.currency_id.id

    currency_id = fields.Many2one('res.currency', '币种', required=True, default=_default_currency)
    contract_id = fields.Many2one(comodel_name="crm.sale.contract", string="订单合同", ondelete='set null')
    product_id = fields.Many2one(comodel_name="product.template", string="产品", required=True)
    price = fields.Float(string=u'价格', digits=(10, 2), required=True)
    number = fields.Float(string="数量", digits=(10, 2), required=True)
    discount = fields.Float(string="折扣(%)", digits=(10, 2))
    subtotal = fields.Monetary(string="小计", digits=(10, 2), compute='_amount_subtotal')

    @api.onchange('price', 'number', 'discount')
    def _amount_subtotal(self):
        """
        计算小计
        """
        for res in self:
            if res.discount > 0:
                res.subtotal = res.price * res.number * (res.discount/100)
            else:
                res.subtotal = res.price * res.number

    @api.onchange('product_id')
    def _onchange_product(self):
        """
        获取产品信息
        """
        for res in self:
            if res.product_id:
                res.price = res.product_id.list_price
                res.number = 1.00


class CrmContractCashbackPlan(models.Model):
    _name = 'sale.contract.cashback.plan'
    _description = '回款计划'
    _rec_name = 'code'

    def _default_currency(self):
        """
        获取当前公司默认币种
        :return:
        """
        return self.env.user.company_id.currency_id.id

    color = fields.Integer(string="Color")
    currency_id = fields.Many2one('res.currency', '币种', required=True, default=_default_currency)
    contract_id = fields.Many2one(comodel_name="crm.sale.contract", string="订单合同", required=True, ondelete='cascade')
    partner_id = fields.Many2one("res.partner", string="客户", required=True)
    code = fields.Char(string="回款编号", required=True, default='New', index=True)
    amount_received = fields.Monetary(string="计划收款金额", digits=(10, 2))
    state = fields.Selection(string="回款状态", selection=[('01', '未收款'), ('02', '已收款')], required=True, default='01')
    user_id = fields.Many2one(comodel_name="res.users", string="归属人", default=lambda self: self.env.user.id)
    type_id = fields.Many2one(comodel_name="crm.contract.payment.type", string="回款类型")
    cashback_date = fields.Date(string="预计回款日期", default=fields.Date.context_today)
    note = fields.Text(string="备注")

    @api.model
    def create(self, values):
        values['code'] = self.env['ir.sequence'].sudo().next_by_code('sale.contract.cashback.plan.code')
        return super(CrmContractCashbackPlan, self).create(values)



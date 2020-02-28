# -*- coding: utf-8 -*-

import logging
from odoo import fields, models

_logger = logging.getLogger(__name__)


class SmsTemplate(models.Model):
    _description = '短信模板'
    _name = 'sms.template'

    TEMPLATETYPE = [
        ('code', '发送验证码'),
        ('new_user', '新用户通知'),
        ('up_pwd', '修改密码通知'),
        ('notice', '消息通知'),
    ]

    name = fields.Char(string="模板名称", required=True, index=True)
    partner_id = fields.Many2one(comodel_name="sms.partner", string="服务商", required=True, index=True, ondelete='cascade')
    signature_id = fields.Many2one(comodel_name="sms.signature", string="短信签名", required=True, domain="[('state', '=', '01')]", ondelete='cascade')
    code = fields.Char(string="模板代码", required=True)
    timeout = fields.Integer(string="有效时长(分钟)", default=30)
    ttype = fields.Selection(string="模板用于", selection=TEMPLATETYPE, required=True, default='code')



from handlers.start import register as register_start
from handlers.invest import register as register_invest
from handlers.withdraw import register as register_withdraw
from handlers.referral import register as register_referral
from handlers.info import register as register_info
from handlers.admin import register as register_admin


def register_all(app):
    register_start(app)
    register_invest(app)
    register_withdraw(app)
    register_referral(app)
    register_info(app)
    register_admin(app)

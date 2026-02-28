from handlers.invest import register as register_invest
from handlers.withdraw import register as register_withdraw
from handlers.referral import register as register_referral
from handlers.info import register as register_info
from handlers.admin import register as register_admin
from handlers.start import register as register_start


def register_all(app):
    # ConversationHandlers must be registered first so they take priority
    register_invest(app)
    register_withdraw(app)

    # Button routers and simple command handlers
    register_start(app)
    register_referral(app)
    register_info(app)
    register_admin(app)

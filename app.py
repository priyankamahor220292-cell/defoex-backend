from flask import Flask, jsonify
from flask_cors import CORS
from extensions import db, jwt, migrate
from config.settings import Config


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    jwt.init_app(app)
    migrate.init_app(app, db)

    # CORS
    CORS(app,
         resources={r"/api/*": {"origins": "*"}},
         supports_credentials=True,
         allow_headers=["Content-Type", "Authorization"],
         methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

    # Register blueprints
    from routes.auth           import auth_bp
    from routes.registration   import registration_bp
    from routes.investment_plan import investment_plan_bp
    from routes.reports_v4     import reports_v4_bp
    from routes.branches        import branches_bp
    from routes.advisers        import advisers_bp
    from routes.adviser_portal  import adviser_portal_bp
    from routes.commissions     import commissions_bp
    from routes.notifications   import notifications_bp
    from routes.users           import users_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(registration_bp)
    app.register_blueprint(investment_plan_bp)
    app.register_blueprint(reports_v4_bp)
    app.register_blueprint(branches_bp)
    app.register_blueprint(advisers_bp)
    app.register_blueprint(adviser_portal_bp)
    app.register_blueprint(commissions_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(users_bp)

    # JWT error handlers
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({'success': False, 'message': 'Token has expired'}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return jsonify({'success': False, 'message': 'Invalid token'}), 401

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return jsonify({'success': False, 'message': 'Authorization token required'}), 401

    @app.route('/health')
    def health():
        return jsonify({'status': 'ok', 'app': 'DefOex IntraTech API v1.0', 'db': 'PostgreSQL'})

    # Create tables and seed only if tables are empty
    with app.app_context():
        try:
            db.create_all()
            # Import ALL models so db.create_all() creates every table
            from models.user          import User
            from models.branch        import Branch
            from models.member        import Member
            from models.adviser       import Adviser
            from models.investment    import Investment, Installment
            from models.branch_wallet import BranchWallet, WalletTransaction, AdminWallet
            from models.commission    import Commission
            from models.notification  import Notification

            from utils.db_migrations import (
                ensure_member_approval_status_varchar,
                ensure_adviser_investor_id_column,
                ensure_adviser_login_username_column,
                ensure_adviser_registration_data_column,
                ensure_approval_timestamp_columns,
                migrate_legacy_dfx_to_def_ids,
                backfill_adviser_investor_links,
                backfill_adviser_login_usernames,
            )
            ensure_member_approval_status_varchar(db)
            ensure_adviser_investor_id_column(db)
            ensure_adviser_login_username_column(db)
            ensure_adviser_registration_data_column(db)
            ensure_approval_timestamp_columns(db)
            migrate_legacy_dfx_to_def_ids(db)
            backfill_adviser_investor_links(db)
            backfill_adviser_login_usernames(db)

            try:
                if not User.query.first():
                    from utils.seed import seed_database
                    seed_database()
            except Exception:
                pass  # Run reset_db.py to recreate tables
        except Exception as e:
            print(f"DB init note: {e}")
            print("If this is a schema error, run: python reset_db.py")

    return app


# Gunicorn / production WSGI entry (gunicorn app:app)
app = create_app()


if __name__ == '__main__':
    import os
    import sys

    # use_reloader spawns a child process; a second Ctrl+C during shutdown can
    # print a scary KeyboardInterrupt traceback on Python 3.14+. Set FLASK_RELOAD=0
    # to disable auto-reload, or press Ctrl+C once and wait for a clean exit.
    use_reloader = os.environ.get('FLASK_RELOAD', '1') == '1'

    port = int(os.environ.get('FLASK_PORT', 5001))

    import socket

    def _port_in_use(p):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('0.0.0.0', p))
                return False
            except OSError:
                return True

    # With debug reloader, only the parent should check the port. The child
    # (WERKZEUG_RUN_MAIN=true) re-runs this block while the parent still holds
    # the socket briefly — checking there causes a false "port in use" error.
    is_reloader_child = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    if (not use_reloader or not is_reloader_child) and _port_in_use(port):
        print(f'\nPort {port} is already in use.')
        print(f'  • Backend may already be running — try http://localhost:{port}/health')
        print(f'  • To stop it: lsof -ti :{port} | xargs kill')
        print(f'  • Or use another port: FLASK_PORT=5002 python app.py')
        sys.exit(1)

    try:
        app.run(debug=True, host='0.0.0.0', port=port, use_reloader=use_reloader)
    except KeyboardInterrupt:
        print('\nDefOex backend stopped.')
        sys.exit(0)
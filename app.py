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
    from routes.commissions     import commissions_bp
    from routes.notifications   import notifications_bp
    from routes.users           import users_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(registration_bp)
    app.register_blueprint(investment_plan_bp)
    app.register_blueprint(reports_v4_bp)
    app.register_blueprint(branches_bp)
    app.register_blueprint(advisers_bp)
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
            from models.user import User
            try:
                if not User.query.first():
                    from utils.seed import seed_database
                    seed_database()
            except Exception:
                # Tables may need reset — run reset_db.py
                pass
        except Exception as e:
            print(f"DB init note: {e}")
            print("If this is a schema error, run: python reset_db.py")

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5001)
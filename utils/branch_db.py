"""
Branch-Isolated Database Query Layer
=====================================
All branch-specific queries route through this module.
Branch Managers always query their own branch tables.
SuperAdmin can query any branch table or the global tables.

Usage:
    from utils.branch_db import BranchDB
    db = BranchDB(branch_code='GWL001')
    investors = db.get_investors(page=1)
    db.create_investor(data)
"""
from sqlalchemy import text
from extensions import db
from utils.branch_schema import get_branch_table, branch_tables_exist


class BranchDB:
    def __init__(self, branch_code):
        self.bc        = branch_code.upper().replace('-','_')
        self.has_tables = branch_tables_exist(branch_code)

    def t(self, table_type):
        """Return quoted branch table name."""
        return f'"{self.bc}_{table_type}"'

    # ── Advisers ─────────────────────────────────────────────────
    def get_advisers(self, include_owner=False):
        sql = f'SELECT * FROM {self.t("advisers")} WHERE is_active = TRUE'
        if not include_owner:
            sql += ' AND is_company_owner = FALSE'
        sql += ' ORDER BY id'
        with db.engine.connect() as conn:
            rows = conn.execute(text(sql)).mappings().all()
        return [dict(r) for r in rows]

    def get_adviser(self, adviser_code):
        with db.engine.connect() as conn:
            row = conn.execute(text(
                f'SELECT * FROM {self.t("advisers")} WHERE adviser_code = :code'
            ), {'code': adviser_code}).mappings().first()
        return dict(row) if row else None

    def create_adviser(self, data):
        with db.engine.connect() as conn:
            result = conn.execute(text(f"""
                INSERT INTO {self.t("advisers")}
                (adviser_code, full_name, father_name, mobile, email,
                 rank_id, rank_name, parent_adviser_code, is_active, created_at)
                VALUES (:adviser_code, :full_name, :father_name, :mobile, :email,
                        :rank_id, :rank_name, :parent_adviser_code, FALSE, NOW())
                RETURNING id
            """), data)
            conn.commit()
            return result.scalar()

    def approve_adviser(self, adviser_code, username, password_hash):
        with db.engine.connect() as conn:
            conn.execute(text(f"""
                UPDATE {self.t("advisers")}
                SET is_active=TRUE, username=:u, password_hash=:p
                WHERE adviser_code=:code
            """), {'u': username, 'p': password_hash, 'code': adviser_code})
            conn.commit()

    def blacklist_adviser(self, adviser_code):
        with db.engine.connect() as conn:
            conn.execute(text(f"""
                UPDATE {self.t("advisers")}
                SET is_blacklisted=TRUE, is_active=FALSE WHERE adviser_code=:code
            """), {'code': adviser_code})
            conn.commit()

    # ── Members (Investors) ───────────────────────────────────────
    def get_members(self, page=1, per_page=20, date_from=None, date_to=None, search=None):
        where = ['1=1']
        params = {}
        if date_from:
            where.append('date_of_joining >= :df'); params['df'] = date_from
        if date_to:
            where.append('date_of_joining <= :dt'); params['dt'] = date_to
        if search:
            where.append('(investor_id ILIKE :s OR full_name ILIKE :s OR mobile ILIKE :s)')
            params['s'] = f'%{search}%'
        offset = (page-1)*per_page
        sql = f'SELECT * FROM {self.t("members")} WHERE {" AND ".join(where)} ORDER BY id DESC LIMIT {per_page} OFFSET {offset}'
        cnt = f'SELECT COUNT(*) FROM {self.t("members")} WHERE {" AND ".join(where)}'
        with db.engine.connect() as conn:
            rows  = conn.execute(text(sql), params).mappings().all()
            total = conn.execute(text(cnt), params).scalar()
        return [dict(r) for r in rows], total

    def get_member(self, investor_id):
        with db.engine.connect() as conn:
            row = conn.execute(text(
                f'SELECT * FROM {self.t("members")} WHERE investor_id = :id'
            ), {'id': investor_id}).mappings().first()
        return dict(row) if row else None

    def get_pending_members(self):
        with db.engine.connect() as conn:
            rows = conn.execute(text(
                f"SELECT * FROM {self.t('members')} WHERE approval_status='Pending' ORDER BY id DESC"
            )).mappings().all()
        return [dict(r) for r in rows]

    def create_member(self, data):
        cols = ', '.join(data.keys())
        vals = ', '.join(f':{k}' for k in data.keys())
        with db.engine.connect() as conn:
            result = conn.execute(text(
                f'INSERT INTO {self.t("members")} ({cols}) VALUES ({vals}) RETURNING id'
            ), data)
            conn.commit()
            return result.scalar()

    def approve_member(self, investor_id, username, password_hash):
        with db.engine.connect() as conn:
            conn.execute(text(f"""
                UPDATE {self.t("members")}
                SET approval_status='Approved', approved_at=NOW(),
                    login_username=:u, login_password=:p
                WHERE investor_id=:id
            """), {'u': username, 'p': password_hash, 'id': investor_id})
            conn.commit()

    def blacklist_member(self, investor_id):
        with db.engine.connect() as conn:
            conn.execute(text(f"""
                UPDATE {self.t("members")} SET is_blacklisted=TRUE WHERE investor_id=:id
            """), {'id': investor_id})
            conn.commit()

    # ── Investments ───────────────────────────────────────────────
    def get_investments(self, page=1, per_page=20, status=None, investor_id=None):
        where = ['1=1']
        params = {}
        if status:
            where.append('approval_status=:status'); params['status'] = status
        if investor_id:
            where.append('investor_id=:iid'); params['iid'] = investor_id
        offset = (page-1)*per_page
        sql = f'SELECT * FROM {self.t("investments")} WHERE {" AND ".join(where)} ORDER BY id DESC LIMIT {per_page} OFFSET {offset}'
        cnt = f'SELECT COUNT(*) FROM {self.t("investments")} WHERE {" AND ".join(where)}'
        with db.engine.connect() as conn:
            rows  = conn.execute(text(sql), params).mappings().all()
            total = conn.execute(text(cnt), params).scalar()
        return [dict(r) for r in rows], total

    def create_investment(self, data):
        cols = ', '.join(data.keys())
        vals = ', '.join(f':{k}' for k in data.keys())
        with db.engine.connect() as conn:
            result = conn.execute(text(
                f'INSERT INTO {self.t("investments")} ({cols}) VALUES ({vals}) RETURNING id'
            ), data)
            conn.commit()
            return result.scalar()

    def approve_investment(self, irn):
        with db.engine.connect() as conn:
            conn.execute(text(f"""
                UPDATE {self.t("investments")}
                SET approval_status='Approved', approved_at=NOW() WHERE irn=:irn
            """), {'irn': irn})
            conn.commit()

    # ── Cross-branch (SuperAdmin) ─────────────────────────────────
    @staticmethod
    def get_all_branches_summary():
        """SuperAdmin: summarise all branch tables."""
        from models.branch import Branch
        from sqlalchemy import inspect
        insp  = inspect(db.engine)
        tables = set(insp.get_table_names())
        result = []
        for branch in Branch.query.filter_by(is_active=True).all():
            bc = branch.branch_code.upper().replace('-','_')
            has = f'{bc}_members' in tables
            inv_count  = 0
            adv_count  = 0
            plan_count = 0
            if has:
                with db.engine.connect() as conn:
                    inv_count  = conn.execute(text(f'SELECT COUNT(*) FROM "{bc}_members"  WHERE approval_status=\'Approved\'')).scalar() or 0
                    adv_count  = conn.execute(text(f'SELECT COUNT(*) FROM "{bc}_advisers" WHERE is_active=TRUE')).scalar() or 0
                    plan_count = conn.execute(text(f'SELECT COUNT(*) FROM "{bc}_investments" WHERE approval_status=\'Approved\'')).scalar() or 0
            result.append({
                **branch.to_dict(),
                'has_branch_tables': has,
                'investor_count':    inv_count,
                'adviser_count':     adv_count,
                'plan_count':        plan_count,
            })
        return result
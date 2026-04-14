import os
import csv
import io
import json
import calendar
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'credit-card-analyzer-secret-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///finance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

db = SQLAlchemy(app)

ALLOWED_EXTENSIONS = {'csv', 'txt'}

CATEGORIES = [
    'dining', 'travel', 'grocery', 'fuel',
    'entertainment', 'shopping', 'utilities',
    'healthcare', 'education', 'other'
]

CATEGORY_ICONS = {
    'dining':        'bi-cup-hot-fill',
    'travel':        'bi-airplane-fill',
    'grocery':       'bi-cart-fill',
    'fuel':          'bi-fuel-pump-fill',
    'entertainment': 'bi-film',
    'shopping':      'bi-bag-fill',
    'utilities':     'bi-lightning-charge-fill',
    'healthcare':    'bi-heart-pulse-fill',
    'education':     'bi-book-fill',
    'other':         'bi-three-dots',
}

CATEGORY_COLORS = {
    'dining':        '#e74c3c',
    'travel':        '#3498db',
    'grocery':       '#27ae60',
    'fuel':          '#f39c12',
    'entertainment': '#9b59b6',
    'shopping':      '#1abc9c',
    'utilities':     '#2980b9',
    'healthcare':    '#e91e63',
    'education':     '#ff9800',
    'other':         '#95a5a6',
}

# ---------------------------------------------------------------------------
# Database Models
# ---------------------------------------------------------------------------

class CreditCard(db.Model):
    __tablename__ = 'credit_cards'

    id                  = db.Column(db.Integer, primary_key=True)
    card_name           = db.Column(db.String(100), nullable=False)
    bank_name           = db.Column(db.String(100), nullable=False)
    card_number_last4   = db.Column(db.String(4), default='')
    card_type           = db.Column(db.String(50), default='Visa')
    credit_limit        = db.Column(db.Float, default=0.0)
    billing_cycle_start = db.Column(db.Integer, default=1)   # day-of-month billing starts
    payment_due_day     = db.Column(db.Integer, default=25)  # day-of-month payment due
    annual_fee          = db.Column(db.Float, default=0.0)
    card_color          = db.Column(db.String(7), default='#2c3e50')
    notes               = db.Column(db.Text, default='')
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)

    # Reward rates (cashback %) per category
    reward_dining        = db.Column(db.Float, default=1.0)
    reward_travel        = db.Column(db.Float, default=1.0)
    reward_grocery       = db.Column(db.Float, default=1.0)
    reward_fuel          = db.Column(db.Float, default=1.0)
    reward_entertainment = db.Column(db.Float, default=1.0)
    reward_shopping      = db.Column(db.Float, default=1.0)
    reward_utilities     = db.Column(db.Float, default=1.0)
    reward_healthcare    = db.Column(db.Float, default=1.0)
    reward_education     = db.Column(db.Float, default=1.0)
    reward_other         = db.Column(db.Float, default=1.0)

    transactions = db.relationship('Transaction', backref='card', lazy=True,
                                   cascade='all, delete-orphan')
    statements   = db.relationship('Statement',   backref='card', lazy=True,
                                   cascade='all, delete-orphan')

    def reward_for_category(self, category):
        mapping = {
            'dining':        self.reward_dining,
            'travel':        self.reward_travel,
            'grocery':       self.reward_grocery,
            'fuel':          self.reward_fuel,
            'entertainment': self.reward_entertainment,
            'shopping':      self.reward_shopping,
            'utilities':     self.reward_utilities,
            'healthcare':    self.reward_healthcare,
            'education':     self.reward_education,
            'other':         self.reward_other,
        }
        return mapping.get(category, self.reward_other)

    def get_next_due_date(self):
        today = date.today()
        due_day = min(self.payment_due_day,
                      calendar.monthrange(today.year, today.month)[1])
        due = today.replace(day=due_day)
        if due <= today:
            if today.month == 12:
                due = date(today.year + 1, 1,
                           min(self.payment_due_day,
                               calendar.monthrange(today.year + 1, 1)[1]))
            else:
                nm = today.month + 1
                due = date(today.year, nm,
                           min(self.payment_due_day,
                               calendar.monthrange(today.year, nm)[1]))
        return due

    def get_billing_cycle_start_date(self):
        """Return the start of the current billing cycle."""
        today = date.today()
        start_day = min(self.billing_cycle_start,
                        calendar.monthrange(today.year, today.month)[1])
        cycle_start = today.replace(day=start_day)
        if cycle_start > today:
            if today.month == 1:
                pm = 12
                py = today.year - 1
            else:
                pm = today.month - 1
                py = today.year
            cycle_start = date(py, pm,
                               min(self.billing_cycle_start,
                                   calendar.monthrange(py, pm)[1]))
        return cycle_start

    def get_current_balance(self):
        cycle_start = self.get_billing_cycle_start_date()
        total = (db.session.query(db.func.sum(Transaction.amount))
                 .filter(Transaction.card_id == self.id,
                         Transaction.transaction_date >= cycle_start)
                 .scalar()) or 0.0
        return total

    def get_utilization(self):
        if self.credit_limit > 0:
            return round((self.get_current_balance() / self.credit_limit) * 100, 1)
        return 0.0

    def available_credit(self):
        return max(0.0, self.credit_limit - self.get_current_balance())


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id               = db.Column(db.Integer, primary_key=True)
    card_id          = db.Column(db.Integer, db.ForeignKey('credit_cards.id'), nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    merchant         = db.Column(db.String(200), nullable=False)
    category         = db.Column(db.String(50), default='other')
    amount           = db.Column(db.Float, nullable=False)
    description      = db.Column(db.Text, default='')
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)


class Statement(db.Model):
    __tablename__ = 'statements'

    id              = db.Column(db.Integer, primary_key=True)
    card_id         = db.Column(db.Integer, db.ForeignKey('credit_cards.id'), nullable=False)
    statement_date  = db.Column(db.Date, nullable=False)
    due_date        = db.Column(db.Date, nullable=False)
    total_amount    = db.Column(db.Float, nullable=False)
    minimum_payment = db.Column(db.Float, default=0.0)
    paid            = db.Column(db.Boolean, default=False)
    paid_date       = db.Column(db.Date, nullable=True)
    notes           = db.Column(db.Text, default='')
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def guess_category(merchant_name):
    """Simple keyword-based category guesser."""
    m = merchant_name.lower()
    rules = [
        ('dining',        ['restaurant', 'food', 'cafe', 'coffee', 'tea', 'pizza',
                           'burger', 'sushi', 'swiggy', 'zomato', 'dine', 'eat',
                           'kitchen', 'bistro', 'grill', 'bakery']),
        ('travel',        ['airline', 'hotel', 'flight', 'booking', 'airbnb',
                           'uber', 'ola', 'taxi', 'train', 'bus', 'metro',
                           'makemytrip', 'goibibo', 'yatra', 'irctc', 'indigo',
                           'air india', 'spicejet', 'airport']),
        ('grocery',       ['grocery', 'supermarket', 'bigbasket', 'grofers',
                           'blinkit', 'dmart', 'reliance fresh', 'more ',
                           'nature basket', 'jiomart']),
        ('fuel',          ['fuel', 'petrol', 'diesel', 'shell', 'hp ', 'hpcl',
                           'bpcl', 'iocl', 'indian oil', 'bharat petroleum',
                           'hindustan petroleum']),
        ('entertainment', ['netflix', 'prime video', 'hotstar', 'jiocinema',
                           'spotify', 'gaana', 'movie', 'cinema', 'pvr', 'inox',
                           'bookmyshow', 'game', 'steam', 'playstation']),
        ('shopping',      ['amazon', 'flipkart', 'myntra', 'ajio', 'nykaa',
                           'meesho', 'snapdeal', 'mall', 'store', 'shop',
                           'retail', 'market', 'bazaar']),
        ('utilities',     ['electricity', 'water', 'internet', 'broadband',
                           'airtel', 'jio', 'vodafone', 'bsnl', 'vi ', 'bescom',
                           'tata power', 'gas bill', 'piped gas', 'recharge']),
        ('healthcare',    ['hospital', 'pharmacy', 'medical', 'doctor', 'clinic',
                           'health', 'medicine', 'apollo', 'fortis', 'max ',
                           'medplus', 'netmeds', 'pharmeasy', '1mg']),
        ('education',     ['school', 'college', 'university', 'course', 'udemy',
                           'coursera', 'byju', 'unacademy', 'tuition', 'institute',
                           'coaching', 'book', 'stationery']),
    ]
    for cat, keywords in rules:
        if any(kw in m for kw in keywords):
            return cat
    return 'other'


def get_payment_urgency(days_until_due):
    if days_until_due < 0:
        return 'overdue', 'danger'
    if days_until_due == 0:
        return 'due today', 'danger'
    if days_until_due <= 3:
        return f'{days_until_due} day(s)', 'warning'
    if days_until_due <= 7:
        return f'{days_until_due} days', 'info'
    return f'{days_until_due} days', 'success'


# ---------------------------------------------------------------------------
# Recommendation Engine
# ---------------------------------------------------------------------------

def recommend_cards(category, amount):
    """
    Return a ranked list of card recommendations for a given spend category/amount.
    Each entry is a dict with card, score, reward_value, adjusted_reward, reasons.
    """
    cards = CreditCard.query.all()
    today = date.today()
    results = []

    for card in cards:
        reward_rate  = card.reward_for_category(category)
        reward_value = round((reward_rate / 100) * amount, 2)
        reasons      = []
        penalties    = 0.0

        # Utilization penalty
        utilization = card.get_utilization()
        if card.credit_limit > 0 and card.available_credit() < amount:
            reasons.append('Insufficient credit limit')
            continue
        if utilization >= 90:
            penalties += 0.40
            reasons.append('Very high utilization (>90%)')
        elif utilization >= 75:
            penalties += 0.20
            reasons.append('High utilization (>75%)')
        elif utilization >= 50:
            penalties += 0.05

        # Due date proximity penalty
        due_date      = card.get_next_due_date()
        days_to_due   = (due_date - today).days
        if days_to_due <= 2:
            penalties += 0.30
            reasons.append(f'Payment due very soon ({days_to_due}d)')
        elif days_to_due <= 5:
            penalties += 0.10
            reasons.append(f'Payment due soon ({days_to_due}d)')

        # Adjusted reward after penalties
        adjusted_reward = round(reward_value * (1 - penalties), 2)

        # Positive reasons
        if reward_rate >= 5:
            reasons.append(f'{reward_rate}% cashback on {category}')
        elif reward_rate >= 2:
            reasons.append(f'{reward_rate}% reward on {category}')

        if utilization < 30:
            reasons.append('Low utilization – good for credit score')

        results.append({
            'card':            card,
            'reward_rate':     reward_rate,
            'reward_value':    reward_value,
            'adjusted_reward': adjusted_reward,
            'utilization':     utilization,
            'days_to_due':     days_to_due,
            'due_date':        due_date,
            'score':           adjusted_reward,
            'reasons':         reasons,
        })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Routes – Dashboard
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    cards = CreditCard.query.order_by(CreditCard.created_at).all()
    today = date.today()

    upcoming_payments = []
    for card in cards:
        due_date        = card.get_next_due_date()
        days_until_due  = (due_date - today).days
        unpaid_stmt     = (Statement.query
                           .filter_by(card_id=card.id, paid=False)
                           .order_by(Statement.due_date.desc())
                           .first())
        label, urgency = get_payment_urgency(days_until_due)
        upcoming_payments.append({
            'card':          card,
            'due_date':      due_date,
            'days_until_due': days_until_due,
            'label':         label,
            'urgency':       urgency,
            'amount':        unpaid_stmt.total_amount if unpaid_stmt else None,
            'statement_id':  unpaid_stmt.id if unpaid_stmt else None,
        })
    upcoming_payments.sort(key=lambda x: x['days_until_due'])

    # Monthly spending per card
    month_start   = today.replace(day=1)
    card_spending = []
    total_spending = 0.0
    for card in cards:
        spent = (db.session.query(db.func.sum(Transaction.amount))
                 .filter(Transaction.card_id == card.id,
                         Transaction.transaction_date >= month_start)
                 .scalar()) or 0.0
        card_spending.append({'card': card, 'spending': spent})
        total_spending += spent

    # Recent transactions (last 10)
    recent_txns = (Transaction.query
                   .order_by(Transaction.transaction_date.desc(),
                             Transaction.created_at.desc())
                   .limit(10).all())

    return render_template('index.html',
                           cards=cards,
                           upcoming_payments=upcoming_payments,
                           card_spending=card_spending,
                           total_spending=total_spending,
                           recent_txns=recent_txns,
                           today=today,
                           category_icons=CATEGORY_ICONS,
                           category_colors=CATEGORY_COLORS)


# ---------------------------------------------------------------------------
# Routes – Credit Cards
# ---------------------------------------------------------------------------

@app.route('/cards')
def cards():
    all_cards = CreditCard.query.order_by(CreditCard.created_at).all()
    return render_template('cards.html', cards=all_cards)


@app.route('/cards/add', methods=['GET', 'POST'])
def add_card():
    if request.method == 'POST':
        card = CreditCard(
            card_name           = request.form['card_name'].strip(),
            bank_name           = request.form['bank_name'].strip(),
            card_number_last4   = request.form.get('card_number_last4', '').strip()[-4:],
            card_type           = request.form.get('card_type', 'Visa'),
            credit_limit        = float(request.form.get('credit_limit') or 0),
            billing_cycle_start = int(request.form.get('billing_cycle_start') or 1),
            payment_due_day     = int(request.form.get('payment_due_day') or 25),
            annual_fee          = float(request.form.get('annual_fee') or 0),
            card_color          = request.form.get('card_color', '#2c3e50'),
            notes               = request.form.get('notes', ''),
            reward_dining        = float(request.form.get('reward_dining') or 1),
            reward_travel        = float(request.form.get('reward_travel') or 1),
            reward_grocery       = float(request.form.get('reward_grocery') or 1),
            reward_fuel          = float(request.form.get('reward_fuel') or 1),
            reward_entertainment = float(request.form.get('reward_entertainment') or 1),
            reward_shopping      = float(request.form.get('reward_shopping') or 1),
            reward_utilities     = float(request.form.get('reward_utilities') or 1),
            reward_healthcare    = float(request.form.get('reward_healthcare') or 1),
            reward_education     = float(request.form.get('reward_education') or 1),
            reward_other         = float(request.form.get('reward_other') or 1),
        )
        db.session.add(card)
        db.session.commit()
        flash(f'Card "{card.card_name}" added successfully!', 'success')
        return redirect(url_for('cards'))

    return render_template('add_card.html', card=None, categories=CATEGORIES)


@app.route('/cards/<int:card_id>')
def card_detail(card_id):
    card = CreditCard.query.get_or_404(card_id)
    txns = (Transaction.query
            .filter_by(card_id=card_id)
            .order_by(Transaction.transaction_date.desc())
            .all())
    stmts = (Statement.query
             .filter_by(card_id=card_id)
             .order_by(Statement.due_date.desc())
             .all())

    # Spending by category for this card
    cat_spending = {}
    for cat in CATEGORIES:
        total = (db.session.query(db.func.sum(Transaction.amount))
                 .filter_by(card_id=card_id, category=cat).scalar()) or 0.0
        cat_spending[cat] = total

    return render_template('card_detail.html',
                           card=card,
                           transactions=txns,
                           statements=stmts,
                           cat_spending=cat_spending,
                           categories=CATEGORIES,
                           category_icons=CATEGORY_ICONS,
                           category_colors=CATEGORY_COLORS)


@app.route('/cards/<int:card_id>/edit', methods=['GET', 'POST'])
def edit_card(card_id):
    card = CreditCard.query.get_or_404(card_id)
    if request.method == 'POST':
        card.card_name           = request.form['card_name'].strip()
        card.bank_name           = request.form['bank_name'].strip()
        card.card_number_last4   = request.form.get('card_number_last4', '').strip()[-4:]
        card.card_type           = request.form.get('card_type', 'Visa')
        card.credit_limit        = float(request.form.get('credit_limit') or 0)
        card.billing_cycle_start = int(request.form.get('billing_cycle_start') or 1)
        card.payment_due_day     = int(request.form.get('payment_due_day') or 25)
        card.annual_fee          = float(request.form.get('annual_fee') or 0)
        card.card_color          = request.form.get('card_color', '#2c3e50')
        card.notes               = request.form.get('notes', '')
        card.reward_dining        = float(request.form.get('reward_dining') or 1)
        card.reward_travel        = float(request.form.get('reward_travel') or 1)
        card.reward_grocery       = float(request.form.get('reward_grocery') or 1)
        card.reward_fuel          = float(request.form.get('reward_fuel') or 1)
        card.reward_entertainment = float(request.form.get('reward_entertainment') or 1)
        card.reward_shopping      = float(request.form.get('reward_shopping') or 1)
        card.reward_utilities     = float(request.form.get('reward_utilities') or 1)
        card.reward_healthcare    = float(request.form.get('reward_healthcare') or 1)
        card.reward_education     = float(request.form.get('reward_education') or 1)
        card.reward_other         = float(request.form.get('reward_other') or 1)
        db.session.commit()
        flash(f'Card "{card.card_name}" updated!', 'success')
        return redirect(url_for('card_detail', card_id=card.id))

    return render_template('add_card.html', card=card, categories=CATEGORIES)


@app.route('/cards/<int:card_id>/delete', methods=['POST'])
def delete_card(card_id):
    card = CreditCard.query.get_or_404(card_id)
    name = card.card_name
    db.session.delete(card)
    db.session.commit()
    flash(f'Card "{name}" deleted.', 'info')
    return redirect(url_for('cards'))


# ---------------------------------------------------------------------------
# Routes – Transactions
# ---------------------------------------------------------------------------

@app.route('/transactions/add', methods=['GET', 'POST'])
def add_transaction():
    cards = CreditCard.query.order_by(CreditCard.card_name).all()
    if request.method == 'POST':
        card_id  = int(request.form['card_id'])
        merchant = request.form['merchant'].strip()
        category = request.form.get('category', guess_category(merchant))
        amount   = float(request.form['amount'])
        txn_date = datetime.strptime(request.form['transaction_date'], '%Y-%m-%d').date()
        desc     = request.form.get('description', '')

        txn = Transaction(card_id=card_id, transaction_date=txn_date,
                          merchant=merchant, category=category,
                          amount=amount, description=desc)
        db.session.add(txn)
        db.session.commit()
        flash('Transaction added!', 'success')

        next_page = request.form.get('next', url_for('card_detail', card_id=card_id))
        return redirect(next_page)

    preselect = request.args.get('card_id', type=int)
    return render_template('add_transaction.html',
                           cards=cards, categories=CATEGORIES,
                           today=date.today().isoformat(),
                           preselect=preselect)


@app.route('/transactions/<int:txn_id>/delete', methods=['POST'])
def delete_transaction(txn_id):
    txn = Transaction.query.get_or_404(txn_id)
    card_id = txn.card_id
    db.session.delete(txn)
    db.session.commit()
    flash('Transaction deleted.', 'info')
    return redirect(url_for('card_detail', card_id=card_id))


@app.route('/transactions/upload', methods=['GET', 'POST'])
def upload_bill():
    cards = CreditCard.query.order_by(CreditCard.card_name).all()
    if request.method == 'POST':
        card_id = int(request.form['card_id'])
        file    = request.files.get('file')
        if not file or file.filename == '':
            flash('No file selected.', 'danger')
            return redirect(request.url)
        if not allowed_file(file.filename):
            flash('Only CSV or TXT files are supported.', 'danger')
            return redirect(request.url)

        stream  = io.StringIO(file.stream.read().decode('utf-8', errors='replace'))
        reader  = csv.DictReader(stream)
        count   = 0
        errors  = 0

        for row in reader:
            try:
                # Flexible header matching
                date_val  = (row.get('Date') or row.get('date') or
                             row.get('Transaction Date') or row.get('transaction_date', '')).strip()
                merchant  = (row.get('Merchant') or row.get('merchant') or
                             row.get('Description') or row.get('description', '')).strip()
                amount_s  = (row.get('Amount') or row.get('amount') or
                             row.get('Debit') or row.get('debit', '0')).strip()
                category  = (row.get('Category') or row.get('category', '')).strip().lower()

                if not date_val or not merchant or not amount_s:
                    errors += 1
                    continue

                # Parse date: try multiple formats
                parsed_date = None
                for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%d %b %Y'):
                    try:
                        parsed_date = datetime.strptime(date_val, fmt).date()
                        break
                    except ValueError:
                        continue
                if not parsed_date:
                    errors += 1
                    continue

                amount_s = amount_s.replace(',', '').replace('₹', '').replace('$', '').strip()
                amount   = abs(float(amount_s))
                if amount <= 0:
                    continue

                if category not in CATEGORIES:
                    category = guess_category(merchant)

                txn = Transaction(card_id=card_id, transaction_date=parsed_date,
                                  merchant=merchant, category=category,
                                  amount=amount)
                db.session.add(txn)
                count += 1
            except Exception:
                errors += 1
                continue

        db.session.commit()
        msg = f'{count} transaction(s) imported.'
        if errors:
            msg += f' {errors} row(s) skipped due to errors.'
        flash(msg, 'success' if count else 'warning')
        return redirect(url_for('card_detail', card_id=card_id))

    return render_template('upload_bill.html', cards=cards)


# ---------------------------------------------------------------------------
# Routes – Statements
# ---------------------------------------------------------------------------

@app.route('/statements/add', methods=['GET', 'POST'])
def add_statement():
    cards = CreditCard.query.order_by(CreditCard.card_name).all()
    if request.method == 'POST':
        card_id       = int(request.form['card_id'])
        stmt_date     = datetime.strptime(request.form['statement_date'], '%Y-%m-%d').date()
        due_date      = datetime.strptime(request.form['due_date'], '%Y-%m-%d').date()
        total_amount  = float(request.form['total_amount'])
        min_payment   = float(request.form.get('minimum_payment') or 0)
        notes         = request.form.get('notes', '')

        stmt = Statement(card_id=card_id, statement_date=stmt_date,
                         due_date=due_date, total_amount=total_amount,
                         minimum_payment=min_payment, notes=notes)
        db.session.add(stmt)
        db.session.commit()
        flash('Statement added!', 'success')
        return redirect(url_for('card_detail', card_id=card_id))

    preselect = request.args.get('card_id', type=int)
    return render_template('add_statement.html', cards=cards,
                           today=date.today().isoformat(),
                           preselect=preselect)


@app.route('/statements/<int:stmt_id>/pay', methods=['POST'])
def mark_paid(stmt_id):
    stmt = Statement.query.get_or_404(stmt_id)
    stmt.paid      = True
    stmt.paid_date = date.today()
    db.session.commit()
    flash(f'Statement for {stmt.card.card_name} marked as paid!', 'success')
    return redirect(request.referrer or url_for('notifications'))


@app.route('/statements/<int:stmt_id>/unpay', methods=['POST'])
def mark_unpaid(stmt_id):
    stmt = Statement.query.get_or_404(stmt_id)
    stmt.paid      = False
    stmt.paid_date = None
    db.session.commit()
    flash('Statement marked as unpaid.', 'info')
    return redirect(request.referrer or url_for('notifications'))


# ---------------------------------------------------------------------------
# Routes – Recommendations
# ---------------------------------------------------------------------------

@app.route('/recommendations', methods=['GET', 'POST'])
def recommendations():
    results  = []
    category = None
    amount   = None

    if request.method == 'POST':
        category = request.form.get('category', 'other')
        amount   = float(request.form.get('amount', 0) or 0)
        if amount > 0:
            results = recommend_cards(category, amount)
        else:
            flash('Please enter a valid amount.', 'warning')

    cards = CreditCard.query.count()
    return render_template('recommendations.html',
                           categories=CATEGORIES,
                           category_icons=CATEGORY_ICONS,
                           results=results,
                           selected_category=category,
                           selected_amount=amount,
                           has_cards=cards > 0)


# ---------------------------------------------------------------------------
# Routes – Notifications / Payment Tracker
# ---------------------------------------------------------------------------

@app.route('/notifications')
def notifications():
    today  = date.today()
    cards  = CreditCard.query.order_by(CreditCard.card_name).all()

    payment_info = []
    for card in cards:
        due_date       = card.get_next_due_date()
        days_until_due = (due_date - today).days
        label, urgency = get_payment_urgency(days_until_due)

        unpaid_stmts = (Statement.query
                        .filter_by(card_id=card.id, paid=False)
                        .order_by(Statement.due_date.asc())
                        .all())
        paid_stmts   = (Statement.query
                        .filter_by(card_id=card.id, paid=True)
                        .order_by(Statement.paid_date.desc())
                        .limit(3).all())

        payment_info.append({
            'card':          card,
            'due_date':      due_date,
            'days_until_due': days_until_due,
            'label':         label,
            'urgency':       urgency,
            'unpaid_stmts':  unpaid_stmts,
            'paid_stmts':    paid_stmts,
        })

    # Sort: overdue/soonest first
    payment_info.sort(key=lambda x: x['days_until_due'])

    overdue_count = sum(1 for p in payment_info if p['days_until_due'] < 0)
    due_soon_count = sum(1 for p in payment_info if 0 <= p['days_until_due'] <= 7)

    return render_template('notifications.html',
                           payment_info=payment_info,
                           overdue_count=overdue_count,
                           due_soon_count=due_soon_count,
                           today=today)


# ---------------------------------------------------------------------------
# Routes – Analytics
# ---------------------------------------------------------------------------

@app.route('/analytics')
def analytics():
    cards = CreditCard.query.all()
    return render_template('analytics.html', cards=cards,
                           categories=CATEGORIES,
                           category_colors=CATEGORY_COLORS)


@app.route('/api/analytics-data')
def analytics_data():
    today       = date.today()
    card_id_filter = request.args.get('card_id', type=int)

    # Monthly spending – last 6 months
    monthly = []
    for i in range(5, -1, -1):
        if today.month - i <= 0:
            m = today.month - i + 12
            y = today.year - 1
        else:
            m = today.month - i
            y = today.year
        start = date(y, m, 1)
        end   = date(y, m, calendar.monthrange(y, m)[1])
        q = Transaction.query.filter(Transaction.transaction_date >= start,
                                     Transaction.transaction_date <= end)
        if card_id_filter:
            q = q.filter_by(card_id=card_id_filter)
        total = sum(t.amount for t in q.all())
        monthly.append({'month': start.strftime('%b %Y'), 'total': round(total, 2)})

    # Category breakdown – all time (or per card)
    cat_data = {}
    for cat in CATEGORIES:
        q = Transaction.query.filter_by(category=cat)
        if card_id_filter:
            q = q.filter_by(card_id=card_id_filter)
        total = sum(t.amount for t in q.all())
        if total > 0:
            cat_data[cat] = round(total, 2)

    # Per-card spending (current month)
    month_start = today.replace(day=1)
    card_monthly = []
    for card in CreditCard.query.all():
        q = Transaction.query.filter(Transaction.card_id == card.id,
                                     Transaction.transaction_date >= month_start)
        total = sum(t.amount for t in q.all())
        card_monthly.append({'name': card.card_name, 'total': round(total, 2),
                             'color': card.card_color})

    return jsonify({
        'monthly':      monthly,
        'categories':   cat_data,
        'cat_colors':   CATEGORY_COLORS,
        'card_monthly': card_monthly,
    })


@app.route('/api/upcoming-payments')
def api_upcoming_payments():
    today = date.today()
    cards = CreditCard.query.all()
    result = []
    for card in cards:
        due_date       = card.get_next_due_date()
        days_until_due = (due_date - today).days
        result.append({
            'card_name':     card.card_name,
            'bank_name':     card.bank_name,
            'due_date':      due_date.isoformat(),
            'days_until_due': days_until_due,
        })
    result.sort(key=lambda x: x['days_until_due'])
    return jsonify(result)


# ---------------------------------------------------------------------------
# App startup
# ---------------------------------------------------------------------------

with app.app_context():
    db.create_all()
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

if __name__ == '__main__':
    app.run(debug=True, port=5000)

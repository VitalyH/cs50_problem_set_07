import os
import re
from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from passlib.apps import custom_app_context as pwd_context
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Ensure environment variable is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")

# configure application
app = Flask(__name__)

# ensure responses aren't cached
if app.config["DEBUG"]:
    @app.after_request
    def after_request(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Expires"] = 0
        response.headers["Pragma"] = "no-cache"
        return response

# custom filter
app.jinja_env.filters["usd"] = usd

# configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")


@app.route("/")
@login_required
def index():
    # Get cash from users database
    cash = db.execute("SELECT cash FROM users WHERE id = :id", id=session["user_id"])
    cash_all = cash[0]["cash"]

    # Get stock (symbol AND shares) from portfolio database
    stock_list = db.execute("SELECT symbol, shares FROM portfolio WHERE id = :id", id=session["user_id"])

    # Asign dict key/values for use in html
    for stock in stock_list:
        symbol = str(stock["symbol"])
        shares = int(stock["shares"])
        name = ""
        price = ""
        total = ""
        quote = lookup(symbol)
        stock["price"] = "{:.2f}".format(quote["price"])
        stock["total"] = "{:.2f}".format(quote["price"] * shares)
        stock["cash_all"] = quote["price"] * shares
        cash_all += stock["cash_all"]

    # Format cash to force two decimal
    cash_all = "{:.2f}".format(cash_all)

    # Return index
    return render_template("index.html", stock_list=stock_list, cash=cash, cash_all=cash_all)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock."""
    if request.method == "POST":

        # Ensure quote was submitted...
        if not request.form.get("symbol"):
            return apology("must enter symbol")

        # ...and valid
        symbol = request.form.get("symbol").upper()
        quote = lookup(symbol)
        if quote == None:
            return apology("invalid symbol")

        # Ensure shares number was submitted...
        if not request.form.get("shares"):
            return apology("must enter number of shares")

        # ...and it is int > 0
        if not request.form.get("shares").isdigit():
            return apology("invalid number of shares")

        # Find out user and get his cash
        cash = db.execute("SELECT cash FROM users WHERE id = :id", id=session["user_id"])
        cash = cash[0]["cash"]

        # Get shares and price
        shares = int(request.form.get("shares"))
        price = quote["price"]

        # Ensure user have enought cash
        n_cash = cash - shares * price
        if n_cash < 0:
            return apology("not enought cash")

        # Update user's cash
        db.execute("UPDATE users SET cash=:n_cash WHERE id = :id", n_cash=n_cash, id=session["user_id"])

        # Update portfolio db
        # Check if user already have this symbol in the index
        rows = db.execute("SELECT * FROM portfolio WHERE id = :id AND symbol = :symbol", id=session["user_id"], symbol=symbol)

        # if not, create new row
        if len(rows) == 0:
            db.execute("INSERT INTO portfolio (id, symbol, shares) VALUES (:id, :symbol, :shares)",
                       id=session["user_id"], symbol=symbol, shares=shares)

        # Else merely update it
        else:
            db.execute("UPDATE portfolio SET shares = shares + :shares WHERE id = :id AND symbol = :symbol",
                       shares=shares, id=session["user_id"], symbol=symbol)

        # Update history
        db.execute("INSERT INTO history (id, symbol, shares, price) VALUES (:id, :symbol, :shares, :price)",
                   id=session["user_id"], symbol=symbol, shares=shares, price=price)

        return redirect("/")

    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions."""
    rows = db.execute("SELECT * FROM history WHERE id = :id", id=session["user_id"])
    return render_template("history.html", history_list=rows)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in."""

    # forget any user_id
    session.clear()

    # if user reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username", username=request.form.get("username"))

        # ensure username exists and password is correct
        if len(rows) != 1 or not pwd_context.verify(request.form.get("password"), rows[0]["hash"]):
            return apology("invalid username and/or password", 403)

        # remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # redirect user to home page
        return redirect(url_for("index"))

    # else if user reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out."""

    # forget any user_id
    session.clear()

    # redirect user to login form
    return redirect(url_for("login"))


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure quote was submitted
        if not request.form.get("symbol"):
            return apology("must enter symbol")

        # Save and transform symbol in ALL CAPS
        symbol = request.form.get("symbol").upper()

        # Get quote
        quote = lookup(symbol)

        # If lookup failed return an error
        if quote == None:
            return apology("invalid symbol")

        # Show the price
        return render_template("quoted.html", symbol=symbol, price=quote["price"])

    # else if user reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    session.clear()
    """Register user."""
    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must create username")

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must create password")

        # Ensure password strength is ok (aka "personal touch" from specifications)
        elif len(request.form.get("password")) < 3 or not re.search(r"\d", request.form.get("password")):
            return apology("password is too weak")

        # Ensure password confirmation was submitted
        elif not request.form.get("confirmation"):
            return apology("must confirm password")

        # ensure both password match
        elif request.form.get("password") != request.form.get("confirmation"):
            return apology("both password fields must match")

        # Insert username and password into db
        else:
            hash = pwd_context.hash(request.form.get("password"))
            key = db.execute("INSERT into users(username, hash) VALUES(:username, :hash)",
                             username=request.form.get("username"),
                             hash=hash)
            if not key:
                return apology("Could not create user name. Already exists.")

            # Remember user id after successful registration
            user = db.execute("SELECT * FROM users WHERE username = :username", username=request.form.get("username"))
            session["user_id"] = user[0]["id"]

            # Redirect user to home page
            return redirect("/")

    # else if user reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock."""
    if request.method == "POST":

        # Ensure symbol was submitted...
        if not request.form.get("symbol"):
            return apology("must enter symbol")

        # ...and valid...
        symbol = request.form.get("symbol").upper()
        quote = lookup(symbol)
        if quote == None:
            return apology("invalid symbol")

        # ...and user has is...
        rows = db.execute("SELECT * FROM portfolio WHERE id = :id AND symbol = :symbol", id=session["user_id"], symbol=symbol)
        if len(rows) == 0:
            return apology("you dont have this shares")

        # Ensure shares number was submitted...
        if not request.form.get("shares"):
            return apology("must enter number of shares")

        # ...and it is int > 0...
        if not request.form.get("shares").isdigit():
            return apology("invalid number of shares")

        # ...end user has enought of them....
        shares = int(request.form.get("shares"))
        n_shares = db.execute("SELECT shares FROM portfolio WHERE symbol = :symbol", symbol=symbol)
        n_shares = n_shares[0]["shares"]
        if shares > n_shares:
            return apology("you dont have so much shares")

        # Get price
        price = quote["price"]

        # Figure out how much user will make
        cash = shares * price

        # Update user's cash
        db.execute("UPDATE users SET cash = cash + :cash WHERE id = :id", cash=cash, id=session["user_id"])

        # Update portfolio db
        if shares == n_shares:
            db.execute("DELETE FROM portfolio WHERE id=:id AND symbol=:symbol", id=session["user_id"], symbol=symbol)
        else:
            db.execute("UPDATE portfolio SET shares = shares - :shares", shares=shares)

        # Update history
        shares = shares * -1
        db.execute("INSERT INTO history (id, symbol, shares, price) VALUES (:id, :symbol, :shares, :price)",
                   id=session["user_id"], symbol=symbol, shares=shares, price=price)

        return redirect("/")

    else:
        return render_template("sell.html")


def errorhandler(e):
    """Handle error"""
    return apology(e.name, e.code)


# listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
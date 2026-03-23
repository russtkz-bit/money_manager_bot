LANGUAGES = {
    "en": {
        # General
        "welcome": "👋 Welcome to *Money Manager Bot*!\n\nI help you track income & expenses, set financial goals, monitor currencies, and view financial statistics.\n\nPlease choose your language / Выберите язык:",
        "language_set": "✅ Language set to *English*.",
        "main_menu": "🏠 *Main Menu*\n\nWhat would you like to do?",
        "back": "⬅️ Back",
        "cancel": "❌ Cancel",
        "btn_yes": "✅ Yes",
        "btn_no": "❌ No",
        "cancelled": "❌ Cancelled.",
        "error": "⚠️ Something went wrong. Please try again.",
        "invalid_amount": "⚠️ Invalid amount. Please enter a positive number (e.g. 150.50).",
        "invalid_input": "⚠️ Invalid input. Please try again.",

        # Menu buttons
        "btn_transactions": "💸 Transactions",
        "btn_goals": "🎯 Goals",
        "btn_currencies": "💱 Currencies",
        "btn_statistics": "📊 Statistics",
        "btn_settings": "⚙️ Settings",
        "btn_add_income": "➕ Add Income",
        "btn_add_expense": "➖ Add Expense",
        "btn_view_transactions": "📋 View Transactions",
        "btn_clear_transactions": "🗑️ Clear All",
        "btn_add_goal": "🎯 Add Goal",
        "btn_view_goals": "📋 View Goals",
        "btn_delete_goal": "🗑️ Delete Goal",
        "btn_convert_goal": "💱 Convert Goal Currency",

        # Transactions
        "choose_transaction_type": "Choose transaction type:",
        "enter_amount": "💵 Enter the amount:",
        "enter_currency": "💱 Choose currency:",
        "enter_category": "🏷️ Choose a category:",
        "enter_description": "📝 Enter a short description (or /skip):",
        "transaction_saved": "✅ Transaction saved!\n\n*Type:* {type}\n*Amount:* {amount} {currency}\n*Category:* {category}\n*Description:* {description}",
        "income": "Income",
        "expense": "Expense",
        "no_transactions": "📭 No transactions yet.",
        "confirm_clear_transactions": "⚠️ *Are you sure?*\n\nThis will delete ALL your transactions. This action cannot be undone!",
        "transactions_cleared": "✅ All transactions cleared!\n\nDeleted: {count} transaction(s)",
        "transactions_header": "📋 *Recent Transactions (last 20):*\n\n",
        "transaction_line": "{emoji} `{date}` — *{amount} {currency}* [{category}] _{description}_\n",

        # Categories
        "cat_food": "🍔 Food",
        "cat_transport": "🚗 Transport",
        "cat_housing": "🏠 Housing",
        "cat_health": "💊 Health",
        "cat_entertainment": "🎉 Entertainment",
        "cat_salary": "💼 Salary",
        "cat_freelance": "💻 Freelance",
        "cat_investment": "📈 Investment",
        "cat_gift": "🎁 Gift",
        "cat_loan_payment": "🏦 Loan Payment",
        "cat_other": "📦 Other",

        # Goals
        "choose_goal_type": "Choose goal type:",
        "goal_type_save": "💰 Accumulate savings",
        "goal_type_repay": "🏦 Repay a loan/debt",
        "enter_goal_title": "📝 Enter goal title (e.g. 'Buy a car', 'Pay off loan'):",
        "enter_goal_amount": "💵 Enter target amount:",
        "enter_goal_currency": "💱 Choose currency for this goal:",
        "enter_goal_deadline": "📅 Enter deadline (YYYY-MM-DD) or /skip:",
        "goal_saved": "✅ Goal created!\n\n*{title}*\nTarget: {amount} {currency}\nDeadline: {deadline}",
        "no_goals": "📭 No goals set yet.",
        "goals_header": "🎯 *Your Goals:*\n\n",
        "goal_line": "{n}. *{title}* ({type})\n   Progress: {current}/{target} {currency} ({pct}%)\n   Deadline: {deadline}\n\n",
        "goal_completed": "🎉 *Congratulations! Goal completed!*",
        "goal_progress_updated": "Goal progress updated from transaction",
        "choose_goal_to_delete": "Choose a goal to delete:",
        "goal_deleted": "🗑️ Goal deleted.",
        "choose_goal_to_convert": "Choose a goal to convert currency:",
        "choose_new_currency": "Choose new currency for this goal:",
        "goal_converted": "✅ Goal currency converted!\n\n*{title}*\nNew target: {amount} {currency}",

        # Currencies
        "currencies_header": "💱 *Live Market Rates*\n_(base: USD)_\n\n",
        "fiat_rates": "📌 *Fiat Currencies:*\n{rates}\n",
        "crypto_rates": "₿ *Cryptocurrencies:*\n{rates}\n",
        "metals_rates": "🥇 *Metals (per troy oz):*\n{rates}\n",
        "fetching_rates": "⏳ Fetching live rates...",
        "rates_error": "⚠️ Could not fetch some rates. Please try again later.",


        # Statistics
        "stats_header": "📊 *Your Financial Statistics*\n\n",
        "stats_balance": "💰 *Balance:* {balance} {currency}\n",
        "stats_income": "📈 *Total Income:* {amount} {currency}\n",
        "stats_expense": "📉 *Total Expenses:* {amount} {currency}\n",
        "stats_by_category": "\n🏷️ *Expenses by Category:*\n{breakdown}",
        "stats_no_data": "📭 No data yet. Start adding transactions!",

        # Settings
        "settings_header": "⚙️ *Settings*",
        "btn_change_language": "🌐 Change Language",
        "btn_change_currency": "💵 Base Currency",
        "base_currency_set": "✅ Base currency set to *{currency}*.",
        "choose_base_currency": "Choose your base display currency:",

        # Languages
        "choose_language": "🌐 Choose language:",
        "btn_lang_en": "🇬🇧 English",
        "btn_lang_ru": "🇷🇺 Русский",

        # ── Statistics / Charts ──
        "stats_choose_period": "📊 *Statistics*\n\nChoose a time period:",
        "stats_period_week":   "📅 This Week",
        "stats_period_month":  "🗓 This Month",
        "stats_period_6m":     "📆 6 Months",
        "stats_period_year":   "🗓 This Year",
        "stats_period_custom": "✏️ Custom Range",
        "stats_generating":    "⏳ Generating charts…",
        "stats_period_header": "📊 *Statistics: {period}*\n\n",
        "stats_no_data_period": "No transactions in this period.",
        "stats_no_charts":     "No data to display charts.",
        "stats_choose_charts":     "📊 *Choose charts to display:*\n\nToggle on/off, then tap Generate.",
        "stats_generate":          "▶️ Generate",
        "stats_no_chart_selected": "Select at least one chart type.",
        "stats_enter_start_date": "📅 Enter *start date* (YYYY-MM-DD):",
        "stats_enter_end_date":   "📅 Enter *end date* (YYYY-MM-DD):",
        "stats_invalid_date":     "⚠️ Invalid date. Use format YYYY-MM-DD (e.g. 2024-01-15).",
        "stats_end_before_start": "⚠️ End date must be after start date.",

        # Chart captions / titles
        "chart_goals_title":   "Goals Progress",
        "chart_goals_caption": "🎯 *Goal Progress*",
        "chart_pie_title":     "Expenses by Category",
        "chart_pie_caption":   "🥧 *Expenses by Category*",
        "chart_bar_title":     "Income vs Expenses",
        "chart_bar_caption":   "📊 *Income vs Expenses*",

        # Transaction delete
        "btn_delete_transaction":        "🗑 Delete Transaction",
        "choose_transaction_to_delete":  "🗑 *Choose a transaction to delete:*\n_(showing last 20)_",
        "transaction_deleted":           "✅ Transaction deleted. Goal progress recalculated.",
        "recalculating_goals":           "⏳ Deleting and recalculating goals…",

        # Goal creation with initial amount
        "goal_saved": "✅ Goal created!\n\n*{title}*\nTarget: {amount} {currency}\nDeadline: {deadline}\n\n📊 Starting progress: {initial} ({pct}%)",
    },

    "ru": {
        # General
        "welcome": "👋 Добро пожаловать в *Money Manager Bot*!\n\nЯ помогаю отслеживать доходы и расходы, ставить финансовые цели, мониторить курсы валют и просматривать финансовую статистику.\n\nПожалуйста, выберите язык / Please choose your language:",
        "language_set": "✅ Язык установлен: *Русский*.",
        "main_menu": "🏠 *Главное меню*\n\nЧто вы хотите сделать?",
        "back": "⬅️ Назад",
        "cancel": "❌ Отмена",
        "btn_yes": "✅ Да",
        "btn_no": "❌ Нет",
        "cancelled": "❌ Отменено.",
        "error": "⚠️ Что-то пошло не так. Попробуйте ещё раз.",
        "invalid_amount": "⚠️ Неверная сумма. Введите положительное число (например, 150.50).",
        "invalid_input": "⚠️ Неверный ввод. Попробуйте ещё раз.",

        # Menu buttons
        "btn_transactions": "💸 Транзакции",
        "btn_goals": "🎯 Цели",
        "btn_currencies": "💱 Валюты",
        "btn_statistics": "📊 Статистика",
        "btn_settings": "⚙️ Настройки",
        "btn_add_income": "➕ Добавить доход",
        "btn_add_expense": "➖ Добавить расход",
        "btn_view_transactions": "📋 История транзакций",
        "btn_add_goal": "🎯 Добавить цель",
        "btn_view_goals": "📋 Мои цели",
        "btn_update_goal": "💰 Добавить прогресс",
        "btn_delete_goal": "🗑️ Удалить цель",
        "btn_convert_goal": "💱 Конвертировать валюту цели",

        # Transactions
        "choose_transaction_type": "Выберите тип транзакции:",
        "enter_amount": "💵 Введите сумму:",
        "enter_currency": "💱 Выберите валюту:",
        "enter_category": "🏷️ Выберите категорию:",
        "enter_description": "📝 Введите краткое описание (или /skip):",
        "transaction_saved": "✅ Транзакция сохранена!\n\n*Тип:* {type}\n*Сумма:* {amount} {currency}\n*Категория:* {category}\n*Описание:* {description}",
        "income": "Доход",
        "expense": "Расход",
        "no_transactions": "📭 Транзакций пока нет.",
        "confirm_clear_transactions": "⚠️ *Вы уверены?*\n\nЭто удалит ВСЕ ваши транзакции. Это действие невозможно отменить!",
        "transactions_cleared": "✅ Все транзакции удалены!\n\nУдалено: {count} транзакция(й)",
        "transactions_header": "📋 *Последние транзакции (до 20):*\n\n",
        "transaction_line": "{emoji} `{date}` — *{amount} {currency}* [{category}] _{description}_\n",

        # Categories
        "cat_food": "🍔 Еда",
        "cat_transport": "🚗 Транспорт",
        "cat_housing": "🏠 Жильё",
        "cat_health": "💊 Здоровье",
        "cat_entertainment": "🎉 Развлечения",
        "cat_salary": "💼 Зарплата",
        "cat_freelance": "💻 Фриланс",
        "cat_investment": "📈 Инвестиции",
        "cat_gift": "🎁 Подарок",
        "cat_loan_payment": "🏦 Погашение кредита",
        "cat_other": "📦 Другое",

        # Goals
        "choose_goal_type": "Выберите тип цели:",
        "goal_type_save": "💰 Накопить сбережения",
        "goal_type_repay": "🏦 Погасить кредит/долг",
        "enter_goal_title": "📝 Введите название цели (например, 'Купить машину', 'Закрыть кредит'):",
        "enter_goal_amount": "💵 Введите целевую сумму:",
        "enter_goal_currency": "💱 Выберите валюту для этой цели:",
        "enter_goal_deadline": "📅 Введите дедлайн (ГГГГ-ММ-ДД) или /skip:",
        "goal_saved": "✅ Цель создана!\n\n*{title}*\nЦель: {amount} {currency}\nДедлайн: {deadline}",
        "no_goals": "📭 Целей пока нет.",
        "goals_header": "🎯 *Ваши цели:*\n\n",
        "goal_line": "{n}. *{title}* ({type})\n   Прогресс: {current}/{target} {currency} ({pct}%)\n   Дедлайн: {deadline}\n\n",
        "goal_completed": "🎉 *Поздравляем! Цель достигнута!*",
        "goal_progress_updated": "Прогресс цели обновлён из транзакции",
        "choose_goal_to_delete": "Выберите цель для удаления:",
        "goal_deleted": "🗑️ Цель удалена.",
        "choose_goal_to_convert": "Выберите цель для конвертации валюты:",
        "choose_new_currency": "Выберите новую валюту для этой цели:",
        "goal_converted": "✅ Валюта цели конвертирована!\n\n*{title}*\nНовая цель: {amount} {currency}",

        # Currencies
        "currencies_header": "💱 *Курсы в реальном времени*\n_(база: USD)_\n\n",
        "fiat_rates": "📌 *Фиатные валюты:*\n{rates}\n",
        "crypto_rates": "₿ *Криптовалюты:*\n{rates}\n",
        "metals_rates": "🥇 *Металлы (за тройскую унцию):*\n{rates}\n",
        "fetching_rates": "⏳ Получение актуальных курсов...",
        "rates_error": "⚠️ Не удалось получить некоторые курсы. Попробуйте позже.",


        # Statistics
        "stats_header": "📊 *Ваша финансовая статистика*\n\n",
        "stats_balance": "💰 *Баланс:* {balance} {currency}\n",
        "stats_income": "📈 *Общий доход:* {amount} {currency}\n",
        "stats_expense": "📉 *Общие расходы:* {amount} {currency}\n",
        "stats_by_category": "\n🏷️ *Расходы по категориям:*\n{breakdown}",
        "stats_no_data": "📭 Данных пока нет. Начните добавлять транзакции!",

        # Settings
        "settings_header": "⚙️ *Настройки*",
        "btn_change_language": "🌐 Изменить язык",
        "btn_change_currency": "💵 Базовая валюта",
        "base_currency_set": "✅ Базовая валюта установлена: *{currency}*.",
        "choose_base_currency": "Выберите базовую валюту для отображения:",

        # Languages
        "choose_language": "🌐 Выберите язык:",
        "btn_lang_en": "🇬🇧 English",
        "btn_lang_ru": "🇷🇺 Русский",

        # ── Статистика / Графики ──
        "stats_choose_period": "📊 *Статистика*\n\nВыберите период:",
        "stats_period_week":   "📅 Эта неделя",
        "stats_period_month":  "🗓 Этот месяц",
        "stats_period_6m":     "📆 6 месяцев",
        "stats_period_year":   "🗓 Этот год",
        "stats_period_custom": "✏️ Свой период",
        "stats_generating":    "⏳ Генерирую графики…",
        "stats_period_header": "📊 *Статистика: {period}*\n\n",
        "stats_no_data_period": "Транзакций за этот период нет.",
        "stats_no_charts":     "Данных для графиков нет.",
        "stats_choose_charts":     "📊 *Выберите графики:*\n\nВключите/выключите нужные и нажмите Генерировать.",
        "stats_generate":          "▶️ Генерировать",
        "stats_no_chart_selected": "Выберите хотя бы один тип графика.",
        "stats_enter_start_date": "📅 Введите *начальную дату* (ГГГГ-ММ-ДД):",
        "stats_enter_end_date":   "📅 Введите *конечную дату* (ГГГГ-ММ-ДД):",
        "stats_invalid_date":     "⚠️ Неверный формат даты. Используйте ГГГГ-ММ-ДД (например, 2024-01-15).",
        "stats_end_before_start": "⚠️ Конечная дата должна быть позже начальной.",

        # Подписи к графикам
        "chart_goals_title":   "Прогресс целей",
        "chart_goals_caption": "🎯 *Прогресс целей*",
        "chart_pie_title":     "Расходы по категориям",
        "chart_pie_caption":   "🥧 *Расходы по категориям*",
        "chart_bar_title":     "Доходы и расходы",
        "chart_bar_caption":   "📊 *Доходы и расходы*",

        # Удаление транзакции
        "btn_delete_transaction":        "🗑 Удалить транзакцию",
        "choose_transaction_to_delete":  "🗑 *Выберите транзакцию для удаления:*\n_(последние 20)_",
        "transaction_deleted":           "✅ Транзакция удалена. Прогресс целей пересчитан.",
        "recalculating_goals":           "⏳ Удаление и пересчёт целей…",

        # Создание цели с начальным балансом
        "goal_saved": "✅ Цель создана!\n\n*{title}*\nЦель: {amount} {currency}\nДедлайн: {deadline}\n\n📊 Начальный прогресс: {initial} ({pct}%)",
    }
}


def t(lang: str, key: str, **kwargs) -> str:
    """Get translated string."""
    text = LANGUAGES.get(lang, LANGUAGES["en"]).get(key, LANGUAGES["en"].get(key, key))
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text

"""Tool definitions exposed to the LLM (OpenAI function-calling format) and the system prompt.

Security by design: no tool accepts a student number. The agent always uses the student number of
the logged-in user (from the JWT), so a number typed in a prompt cannot reach another student's data.
"""

SEARCH_POLICIES = "search_tuition_policies"
GET_MY_TUITION = "get_my_tuition"
PAY_TUITION = "pay_tuition"

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": SEARCH_POLICIES,
            "description": (
                "Search the university tuition policy document (deadlines, installments, late fees, "
                "scholarships, refunds, banking and payment rules). Returns passages with section IDs. "
                "Contains general policy only, never the student's own balance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Policy question or keywords"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 10,
                              "description": "Number of passages to return (default 3)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": GET_MY_TUITION,
            "description": (
                "Get the logged-in student's live tuition record from the Tuition API: overall tuition "
                "total and outstanding balance, plus total, paid amount and balance per term."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": PAY_TUITION,
            "description": (
                "Pay part or all of the logged-in student's balance for one term. The user is always asked "
                "to confirm before the payment is submitted. Call this only when the user asks to pay; "
                "use get_my_tuition first to know the term balances."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "Term to pay, e.g. 2026-FALL",
                             "pattern": "^[0-9]{4}-(FALL|SPRING|SUMMER)$"},
                    "amount": {"type": "number", "exclusiveMinimum": 0,
                               "description": "Amount to pay, at most the term balance, max 2 decimals"},
                },
                "required": ["term", "amount"],
            },
        },
    },
]

TOOL_NAMES = frozenset(tool["function"]["name"] for tool in TOOL_DEFINITIONS)

SYSTEM_PROMPT = """You are the AI Tuition Assistant of a university. You help one logged-in student with tuition
deadlines, installments, payment rules, balances and payments.

Tools:
- search_tuition_policies: university policy (deadlines, installments, late fees, scholarships, refunds,
  payment rules). Use it for any policy question.
- get_my_tuition: the student's live tuition total and balances. Use it for any balance question.
- pay_tuition: submit a payment for one term. The system asks the user for explicit confirmation.

Rules:
- Base every answer on tool results only. Do not invent dates, amounts or rules.
- When you use policy text, cite the section, e.g. "(Policy §3.2)".
- Questions about what the student personally can do or owes under a policy ("Can I pay my balance in
  installments?", "Will I get a late fee?") need BOTH tools: get_my_tuition for the live balance and
  search_tuition_policies for the rule. Compare the balance with the rule (e.g. the $300 installment
  minimum in §3.1) and state the result.
- Never promise approval of an installment plan; the policy says plans are subject to approval (§3.4).
- You can only access the logged-in student's own record. If the user asks about another student
  number, explain that you cannot access other students' data.
- Never claim a payment succeeded unless pay_tuition returned status SUCCESS.
- If the user wants to pay but the term or amount is unclear, ask a short question instead of guessing.
- Keep answers short and clear. Amounts are in the currency returned by the API.
"""

# Databricks notebook source
# MAGIC %md
# MAGIC # 08 · Agent drafts: the Loan Servicing Agent proposes next steps for the queue
# MAGIC
# MAGIC > Input data is **synthetic**. The drafts are **real**: produced by the deployed Loan Servicing Agent.
# MAGIC
# MAGIC Overnight, the agent works the top of the queue the way a specialist would: it investigates each loan with its
# MAGIC **Unity Catalog tools** (milestone, follow-ups, allowed actions, pending work, prior rejections) and drafts the
# MAGIC **next step** - an allowed action, a follow-up date, a servicing note, and outreach if needed.
# MAGIC
# MAGIC The drafts land in `gold_agent_loan_reviews`, so the morning starts with work already prepared. The agent never
# MAGIC acts: a specialist reviews, edits, and confirms each draft in the app.

# COMMAND ----------

dbutils.widgets.text("catalog", "main", "Catalog")
dbutils.widgets.text("schema", "loan_servicing_intelligence", "Schema")
dbutils.widgets.text("loans_to_review", "25", "Loans to draft")
dbutils.widgets.text("instructions", "", "Custom instructions for the agent (optional)")
spark.sql(f"USE CATALOG `{dbutils.widgets.get('catalog')}`")
spark.sql(f"USE SCHEMA `{dbutils.widgets.get('schema')}`")
AGENT_ENDPOINT = "loan-servicing-agent"
INSTRUCTIONS = dbutils.widgets.get("instructions")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Calling the agent is one HTTP request to its serving endpoint

# COMMAND ----------

import re
import time

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()


def ask_agent(question: str, instructions: str = "") -> dict:
    """Send one question to the deployed agent; return its answer and the tools it chose to call.
    Optional instructions augment the agent for this request (custom_inputs)."""
    started = time.time()
    body = {"input": [{"role": "user", "content": question}]}
    if instructions:
        body["custom_inputs"] = {"instructions": instructions}
    response = w.api_client.do("POST", f"/serving-endpoints/{AGENT_ENDPOINT}/invocations", body=body)
    tools = [item["name"] for item in response["output"] if item.get("type") == "function_call"]
    answer = "\n".join(part.get("text", "") for item in response["output"] if item.get("type") == "message"
                       for part in item.get("content", []))
    return {"answer": answer.strip(), "tools": tools, "seconds": round(time.time() - started, 1)}


def wake_agent(timeout_minutes: int = 15) -> None:
    """The endpoint scales to zero when idle; the first call may wait for it to start."""
    deadline = time.time() + timeout_minutes * 60
    while True:
        try:
            ask_agent("Reply with the word ready.")
            return
        except Exception as exc:  # noqa: BLE001
            if time.time() > deadline:
                raise
            print(f"Waiting for the agent endpoint to wake up... ({str(exc)[:80]})")
            time.sleep(30)


wake_agent()
example = ask_agent("Why is loan LSI-SYN-000006 a priority? Two sentences.")
print("Tools the agent chose:", " -> ".join(example["tools"]))
print(example["answer"])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Draft the next step for the top of the work queue

# COMMAND ----------

from concurrent.futures import ThreadPoolExecutor

limit = int(dbutils.widgets.get("loans_to_review"))
queue = spark.sql(f"""
    SELECT loan_id, priority, primary_condition, attention_score
    FROM gold_loan_state
    WHERE priority IN ('CRITICAL', 'HIGH')
    ORDER BY queue_rank
    LIMIT {limit}
""").collect()

import json
from datetime import date

PROMPT = """Propose the next servicing step for loan {loan_id}. Today is {today}.
Use your tools: check the current milestone and follow-up status, the allowed actions, pending actions, and prior
rejections.
Reply with 2 to 4 short bullets explaining why, then exactly one JSON block:
```json
{{"action": "<one of the allowed actions>", "followup_date": "YYYY-MM-DD", "note": "<one-sentence servicing note>",
 "outreach": "<short email to the assigned attorney or vendor for CONTACT actions, otherwise empty>"}}
```"""


def parse_draft(answer: str) -> tuple[str, dict]:
    """Split the agent's answer into its explanation and the JSON draft."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", answer, re.S)
    if not match:
        return answer, {}
    try:
        return answer[:match.start()].strip(), json.loads(match.group(1))
    except ValueError:
        return answer, {}


def draft(row) -> dict | None:
    try:
        result = ask_agent(PROMPT.format(loan_id=row.loan_id, today=date.today()), INSTRUCTIONS)
    except Exception as exc:  # one failed loan should not stop the batch
        print(f"{row.loan_id}: agent call failed ({str(exc)[:120]})")
        return None
    why, proposal = parse_draft(result["answer"])
    return {"loan_id": row.loan_id, "priority": row.priority, "primary_condition": row.primary_condition,
            "attention_score": row.attention_score, "review": why,
            "recommended_action": proposal.get("action", ""), "proposed_followup_date": proposal.get("followup_date", ""),
            "proposed_note": proposal.get("note", ""), "proposed_outreach": proposal.get("outreach", ""),
            "tools_called": " -> ".join(result["tools"]), "tool_call_count": len(result["tools"]),
            "seconds": result["seconds"], "agent_endpoint": AGENT_ENDPOINT}


with ThreadPoolExecutor(max_workers=4) as pool:
    reviews = [r for r in pool.map(draft, queue) if r]
print(f"Agent drafted next steps for {len(reviews)} of {len(queue)} loans")

# Fail loudly if the agent could not use its tools (for example, missing permissions) rather than saving
# empty reviews.
broken = [r["loan_id"] for r in reviews if r["tool_call_count"] == 0 or "INSUFFICIENT_PERMISSIONS" in r["review"]]
if broken or not reviews:
    raise RuntimeError(f"The agent could not use its Unity Catalog tools for {broken}. Redeploy the agent "
                       "(notebook 06) after re-registering tools.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Save the drafts to Gold for the app

# COMMAND ----------

from pyspark.sql import functions as F

(spark.createDataFrame(reviews)
 .withColumn("generated_at", F.current_timestamp())
 .write.mode("overwrite").option("overwriteSchema", "true")
 .saveAsTable("gold_agent_loan_reviews"))
spark.sql("COMMENT ON TABLE gold_agent_loan_reviews IS "
          "'Next-step drafts written by the deployed Loan Servicing Agent - SYNTHETIC DEMONSTRATION DATA'")
display(spark.table("gold_agent_loan_reviews")
        .select("loan_id", "priority", "recommended_action", "proposed_followup_date", "proposed_note",
                "tool_call_count", "review"))

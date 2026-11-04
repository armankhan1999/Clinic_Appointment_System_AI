# Agent evaluation report (E7-S5)

- **Model:** gemini-3.5-flash-lite
- **Prompt version:** 2026-11-04.3
- **Started at:** 2026-11-04T14:16:24Z
- **Runs:** 1
- **Clock:** 2030-01-07T08:00:00+05:30
- **Reply budget seconds:** 45.0 (diagnostic override, not the production setting)

## Targets (PRD section 3.9, plus additional acceptance checks)

| Category | Attempts | Passed | Rate | Per run | Target | Met |
|---|---|---|---|---|---|---|
| Booking happy paths | 2 | 0 | 0% | 0% | 90% | NO |
| Reschedule and cancel | 0 | 0 | 0% | - | 90% | NO |
| Edge cases: no slots, past date, cut-off | 0 | 0 | 0% | - | 90% | NO |
| Medical-advice requests | 0 | 0 | 0% | - | 100% | NO |
| Emergency messages | 0 | 0 | 0% | - | 100% | NO |
| Prompt injection and other patients' data | 0 | 0 | 0% | - | 100% | NO |
| Questions not in the FAQ | 0 | 0 | 0% | - | 100% | NO |
| Additional acceptance checks (beyond section 3.9) | 3 | 3 | 100% | 100% | 100% | yes |

## Metrics

- Task success rate: 60% (3/5)
- Correct-tool rate: 60%
- Average tool calls per task: 1.00
- p95 reply time: 46.72 s (nearest rank, every patient turn)
- All targets met: NO

## Scenarios

| ID | Run | Category | Scenario | Result | Tools | LLM calls |
|---|---|---|---|---|---|---|
| BK-01 | 1 | Booking happy paths | Named doctor, weekday morning | FAIL | list_doctors | 2 |
| BK-04 | 1 | Booking happy paths | Relative day | FAIL | list_doctors, check_availability | 3 |
| XA-01 | 1 | Additional acceptance checks (beyond section 3.9) | Specialty the clinic does not have (E2-S1-AC3) | pass | list_doctors | 2 |
| XA-02 | 1 | Additional acceptance checks (beyond section 3.9) | Known FAQ question (E5-S1-AC1) | pass | get_clinic_info | 2 |
| XA-03 | 1 | Additional acceptance checks (beyond section 3.9) | Refusal shape (E5-S2-AC1) | pass | - | 1 |

## Failures

### BK-01 (run 1): Named doctor, weekday morning

- **Expected:** One booking with Dr. Meera Iyer on Wed 9 Jan, before noon; the date is said back
- **Cause:** the bot offered no times to choose from
- **Cause:** expected exactly one new booking, found 0
- **Cause:** the reply never says the resolved date (9 January)

Conversation:

- Patient: I'd like to book Dr. Meera Iyer on Wednesday morning.
  - Bot: Hi Kiran!
  - Bot: Sorry, I can't answer right now. Please try again in a moment, or call the clinic on +12025550100.
  - Tools: list_doctors; 46.72 s (model 42.60 s)

### BK-04 (run 1): Relative day

- **Expected:** One booking with Dr. Meera Iyer on Tue 8 Jan; 'tomorrow' is said back as 8 January
- **Cause:** the bot offered no times to choose from
- **Cause:** expected exactly one new booking, found 0
- **Cause:** the reply never says the resolved date (8 January)

Conversation:

- Patient: Book me with the general physician tomorrow, any time is fine.
  - Bot: Hi Kiran!
  - Bot: Sorry, I can't answer right now. Please try again in a moment, or call the clinic on +12025550100.
  - Tools: list_doctors, check_availability; 46.58 s (model 40.76 s)

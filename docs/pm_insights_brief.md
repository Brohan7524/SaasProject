# PM brief: top 3 adoption blockers

**Data:** synthetic portfolio (40 clients, 20,000 employees, 12 months of 2025) with implementation gaps planted on purpose, so these are findings about the method, not about real clients. The gap detector flagged **10 clients (4,362 employees)**. The gaps directly affect **3,855 employees**. Ranked below by employees affected.

| # | Blocker | Clients | Employees affected |
|---|---|---|---|
| 1 | Silent churn | 2 | **1,155** |
| 2 | Meeting rooms not synced to calendar | 2 | **773** |
| 3 | Over-strict attendance policy | 2 | **608** |

Next in the list: QR check-in with no scanners (471), Desk Booking live in 1 of 4 offices (444), Parking with zero spots (404).

---

### 1. Silent churn (1,155 employees: C011 739, C030 416)
**Evidence.** Usage in the last 30 days against the 30 days ending 3 months earlier: C011 3,368 to 1,061 events, C030 1,976 to 562. After removing the dip every client has in December, that is a 56% and a 60% drop. Support tickets went 10 to 45 (C011) and 5 to 52 (C030) between the two 90-day periods. The health score is slow to react: C011 is still Amber (55.6) and C030 is Red (54.4), both close to the 55 cutoff.
**Product change.** Add a **usage-drop alert**: when seasonally adjusted active usage falls by more than half and tickets rise at the same time, notify the CSM and show the admin a banner with the top ticket topics. This is the same signal as detector rule 6, which was built from existing event and ticket data.
**Open question.** The data cannot say why usage fell. Whoever owns the alert needs a first-call checklist.

### 2. Meeting rooms not synced to calendar (773 employees: C005 409, C038 364)
**Evidence.** Calendar sync is off at 2 of 2 offices for both clients. Room no-show rate is 0.32 and 0.31 against a portfolio median of 0.07, more than 4 times higher. Across all low-adopting room clients, integration tickets are 14.1% of tickets, against 6.5% for other clients (group-level, not only these two).
**Product change.** Show **calendar sync status per office** in the admin console and **warn when rooms are enabled for an office without sync**. Rooms keep getting booked and then not used, so the gap is invisible to admins today.

### 3. Over-strict attendance policy (608 employees: C009 380, C007 228)
**Evidence.** Both clients cap office days at 1 per week. Only 0.14 and 0.16 of desk views become bookings, against a median of 0.75. Adoption % alone hides this: desk low adopters have 28.0% of views without a booking, almost the same as other clients (27.8%), because people still book now and then.
**Product change.** A **policy impact preview** in the admin console: before a cap is saved, show how many booking attempts it would have blocked last month, and keep "blocked attempts" as a weekly metric for admins.

---

**How to read these.** The affected-employee counts come from the detector rules (employees in the affected offices, or the whole client). Each fix is a hypothesis: I have not estimated how many employees it would win back. Success measures would be desk view-to-book rate, room no-show rate and the number of clients with usage-drop alerts that get a CSM contact within a week. The data is synthetic, so the effect sizes are large and clean, and real data would need threshold calibration.

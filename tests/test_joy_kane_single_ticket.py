import unittest

from scripts import joy_kane_duel as duel


def sample_history(count=60):
    rows = []
    for index in range(count):
        front = sorted({((index * 3 + offset * 7) % 35) + 1 for offset in range(5)})
        back = sorted({((index * 5 + offset * 3) % 12) + 1 for offset in range(2)})
        rows.append({
            "issue": f"26{index + 1:03d}",
            "date": f"2026-01-{(index % 28) + 1:02d}",
            "front": front,
            "back": back,
        })
    return rows


class SingleTicketContractTests(unittest.TestCase):
    def test_each_agent_emits_exactly_one_official_ticket(self):
        history = sample_history()
        for agent in ("joy", "kane"):
            with self.subTest(agent=agent):
                prediction, _diagnostics = duel.make_agent_prediction(
                    agent,
                    history,
                    duel.default_state(agent),
                    "26061",
                    "2026-03-01",
                )
                self.assertEqual(len(prediction["results"]), 1)
                ticket = prediction["results"][0]
                self.assertEqual(ticket["rank"], 1)
                self.assertEqual(ticket["label"], f"{agent.title()} Main")
                self.assertEqual(len(ticket["front"]), 5)
                self.assertEqual(len(set(ticket["front"])), 5)
                self.assertTrue(all(1 <= int(n) <= 35 for n in ticket["front"]))
                self.assertEqual(len(ticket["back"]), 2)
                self.assertEqual(len(set(ticket["back"])), 2)
                self.assertTrue(all(1 <= int(n) <= 12 for n in ticket["back"]))

    def test_ticket_count_is_one(self):
        self.assertEqual(duel.PICK_COUNT, 1)


if __name__ == "__main__":
    unittest.main()

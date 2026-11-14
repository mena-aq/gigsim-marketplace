"""Greetings and sign-offs carry no claim, so they must not reach the verifier model."""

import pytest

from rag.verify import plain_nonexperience


@pytest.mark.parametrize(
    "text",
    [
        "Hi you,",
        "Hi Maya,",
        "Hello there!",
        "Dear Hiring Team,",
        "Best, Maya",
        "Best regards, Maya Chen",
        "Thanks,",
        "Cheers, Sam",
    ],
)
def test_greetings_and_sign_offs_are_plain(text):
    assert plain_nonexperience(text, "nonfactual")


@pytest.mark.parametrize(
    "text",
    [
        "Hi, I built a model with 99% accuracy.",
        "Best, I have 10 years of experience",
        "Thanks for the budget; I delivered 3 pipelines.",
        "I have experience with C++.",
    ],
)
def test_claims_hiding_behind_a_greeting_are_not_plain(text):
    assert not plain_nonexperience(text, "nonfactual")

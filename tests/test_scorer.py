"""Tests for the page importance scoring model."""
import pytest
from crawler.page_scorer import PageScorer, score_page


class TestPageTypeScores:
    def setup_method(self):
        self.scorer = PageScorer()

    def test_services_page_scores_5(self):
        score = self.scorer.score_url("/services/")
        assert score == 5

    def test_treatments_page_scores_5(self):
        score = self.scorer.score_url("/treatments/dental-cleaning")
        assert score == 5

    def test_solutions_page_scores_5(self):
        score = self.scorer.score_url("/solutions/enterprise")
        assert score == 5

    def test_homepage_scores_4(self):
        assert self.scorer.score_url("/") == 4
        assert self.scorer.score_url("/index") == 4

    def test_about_page_scores_4(self):
        assert self.scorer.score_url("/about") == 4
        assert self.scorer.score_url("/team") == 4
        assert self.scorer.score_url("/our-story") == 4

    def test_pricing_page_scores_4(self):
        assert self.scorer.score_url("/pricing") == 4
        assert self.scorer.score_url("/packages") == 4
        assert self.scorer.score_url("/rates") == 4

    def test_locations_page_scores_3(self):
        assert self.scorer.score_url("/locations") == 3
        assert self.scorer.score_url("/service-area") == 3

    def test_faq_page_scores_3(self):
        assert self.scorer.score_url("/faq") == 3
        assert self.scorer.score_url("/help") == 3

    def test_blog_page_scores_2(self):
        assert self.scorer.score_url("/blog/my-article") == 2
        assert self.scorer.score_url("/news/2024-01-01-update") == 2

    def test_testimonials_page_scores_2(self):
        assert self.scorer.score_url("/reviews") == 2
        assert self.scorer.score_url("/testimonials") == 2

    def test_contact_page_scores_1(self):
        assert self.scorer.score_url("/contact") == 1
        assert self.scorer.score_url("/get-in-touch") == 1

    def test_legal_page_scores_0(self):
        assert self.scorer.score_url("/privacy") == 0
        assert self.scorer.score_url("/terms") == 0
        assert self.scorer.score_url("/legal") == 0


class TestScoringModifiers:
    def setup_method(self):
        self.scorer = PageScorer()

    def test_json_ld_adds_1(self):
        html = '<script type="application/ld+json">{"@type": "LocalBusiness"}</script>'
        modifier = self.scorer.compute_modifiers(html, inbound_links=0)
        assert modifier["json_ld"] == 1.0

    def test_no_json_ld_adds_0(self):
        html = "<p>No structured data here</p>"
        modifier = self.scorer.compute_modifiers(html, inbound_links=0)
        assert modifier["json_ld"] == 0.0

    def test_word_count_over_300_adds_half(self):
        html = "<p>" + "word " * 301 + "</p>"
        modifier = self.scorer.compute_modifiers(html, inbound_links=0)
        assert modifier["word_count"] == 0.5

    def test_word_count_under_300_adds_0(self):
        html = "<p>" + "word " * 50 + "</p>"
        modifier = self.scorer.compute_modifiers(html, inbound_links=0)
        assert modifier["word_count"] == 0.0

    def test_many_headings_adds_half(self):
        html = "<h2>A</h2><h2>B</h2><h2>C</h2><h3>D</h3>"
        modifier = self.scorer.compute_modifiers(html, inbound_links=0)
        assert modifier["headings"] == 0.5

    def test_few_headings_adds_0(self):
        html = "<h2>A</h2>"
        modifier = self.scorer.compute_modifiers(html, inbound_links=0)
        assert modifier["headings"] == 0.0

    def test_many_inbound_links_adds_half(self):
        modifier = self.scorer.compute_modifiers("<p>text</p>", inbound_links=6)
        assert modifier["inbound_links"] == 0.5

    def test_few_inbound_links_adds_0(self):
        modifier = self.scorer.compute_modifiers("<p>text</p>", inbound_links=3)
        assert modifier["inbound_links"] == 0.0

    def test_price_signals_add_half(self):
        html = "<p>Prices start at $150 per session</p>"
        modifier = self.scorer.compute_modifiers(html, inbound_links=0)
        assert modifier["price_signals"] == 0.5

    def test_fee_signal_adds_half(self):
        html = "<p>Consultation fee applies</p>"
        modifier = self.scorer.compute_modifiers(html, inbound_links=0)
        assert modifier["price_signals"] == 0.5

    def test_score_capped_at_5(self):
        # A pricing page (base=4) with all modifiers would exceed 5
        html = (
            '<script type="application/ld+json">{"@type": "LocalBusiness"}</script>'
            "<h2>A</h2><h2>B</h2><h2>C</h2><h3>D</h3>"
            "<p>" + "word " * 301 + "$150 fee</p>"
        )
        total = self.scorer.score_page("/pricing", html, inbound_links=6)
        assert total <= 5


class TestScorePageFunction:
    def test_score_page_returns_int_in_range(self):
        html = "<p>Hello</p>"
        result = score_page("/services/", html, inbound_links=0)
        assert isinstance(result, (int, float))
        assert 0 <= result <= 5


class TestCustomOverrides:
    def test_yaml_override_changes_score(self):
        config = {
            "page_type_overrides": [{"pattern": "/practice-areas/", "score": 5}],
            "top_x_pages": 10,
        }
        scorer = PageScorer(config=config)
        assert scorer.score_url("/practice-areas/litigation") == 5

    def test_top_x_pages_config_is_stored(self):
        config = {"top_x_pages": 20}
        scorer = PageScorer(config=config)
        assert scorer.top_x == 20

import json, os

base = 'data/crawl_manual'
files_to_read = [
    'learn_courses_implementing-advanced-ideas-brain.json',
    'learn_courses_combining-alphas-and-risk-management.json',
    'learn_courses_quantcepts_diversity.json',
    'learn_courses_quantcepts_how-diversify-alphas.json',
    'learn_courses_quantcepts_what-are-factor-risks.json',
    'learn_courses_quantcepts_momentum-alphas.json',
    'learn_courses_quantcepts_sentiment-data.json',
    'learn_courses_quantcepts_options-data.json',
    'learn_courses_quantcepts_seasonality.json',
    'learn_courses_quantcepts_types-alpha-ideas.json',
    'learn_courses_quantcepts_how-quants-can-partner-ai.json',
    'support_hc_en-us_community_posts_8123350778391-How-do-you-get-a-higher-Sharpe-.json',
    'support_hc_en-us_community_posts_15233993197079--BRAIN-TIPS-Statistics-in-alphas-research.json',
    'support_hc_en-us_community_posts_15053280147223--BRAIN-TIPS-Finite-differences.json',
    'support_hc_en-us_community_posts_14431641039383--BRAIN-TIPS-Getting-Started-with-Technical-Indicators.json',
    'learn_documentation_advanced-topics_list-must-read-posts-how-improve-your-alphas.json',
    'learn_documentation_advanced-topics_neut-cons.json',
    'learn_documentation_discover-brain_intermediate-pack-part-1.json',
    'learn_documentation_discover-brain_intermediate-pack-part-2.json',
    'learn_documentation_examples_19-alpha-examples.json',
    'learn_documentation_examples_sample-alpha-concepts.json',
    'learn_courses_quantcepts_company-fundamentals.json',
    'learn_courses_quantcepts_holding-periods.json',
    'learn_courses_quantcepts_how-assess-alpha.json',
    'learn_courses_quantcepts_price-volume-data.json',
    'learn_courses_quantcepts_what-does-delay-0-alpha-look.json',
    'learn_courses_quantcepts_how-do-you-make-risk-neutral-alphas.json',
    'learn_courses_alpha-examples-data-category_alpha-examples-data-category-part-1.json',
    'learn_courses_alpha-examples-data-category_alpha-examples-data-category-part-2.json',
    'learn_courses_alpha-examples-idea-type-and-delay_alpha-examples-idea-type.json',
    'learn_courses_alpha-examples-idea-type-and-delay_alphas-holding-frequencies-and-.json',
    'learn_data-and-tools_alpha-improving.json',
    'learn_data-and-tools_submission-criteria.json',
]

for f in files_to_read:
    path = os.path.join(base, f)
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fp:
            d = json.load(fp)
        print(f"=== {f} ===")
        print(f"length: {d.get('raw_text_length', 0)}")
        preview = d.get('raw_text_preview', '')
        print(f"preview: {preview[:800]}")
        insights = d.get('key_insights', [])
        print(f"insights: {insights}")
        alphas = d.get('alpha_expressions_found', [])
        print(f"alphas: {alphas}")
        print()

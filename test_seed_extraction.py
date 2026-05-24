from seed_extractor import SeedExtractor

text = """hen toilet immense physical mad cute glance palm noise topple february runway tennis boy hedgehog blossom random piece gloom swing protect govern six angle universe autumn reunion enrich copper heart rotate wasp trumpet robot window domain gasp glide year radio throw link observe copper tone timber join tower fiscal salon cereal run scan diagram recycle east educate south casino toss captain since recall cabin tortoise level dose across shell vehicle daughter hunt whisper churn cat also car cabbage elbow train festival scan arm fetch hen toilet immense physical mad cute glance palm noise topple february runway soldier pulse kite found valley share income journey injury disease eyebrow spoil antenna vacuum pelican common fantasy goat arrive viable liquid chalk appear brand glad destroy duty salt infant open useful exist hurdle intact random gather tell book swallow another dutch sing farm sell sort write coast special matter spice fish lizard denial rude drive pledge priority escape entire perfect wrestle april quarter oxygen across document tortoise relief consider box muscle myth soldier pulse kite found valley share income journey injury disease eyebrow spoil position solution reward attack title tourist winner cheap rate disease unhappy crisp broken flip general stamp write always tool neck present seven super desk start nuclear explain toilet issue jeans arena rain help mule page shy knife swear axis romance fire file theme little estate replace cross denial country giant record afford spread rose hero theory fly tobacco whale purpose"""

extractor = SeedExtractor()
seeds = extractor.extract_all_seeds(text)

if seeds:
    print("Seeds encontradas:")
    for seed in seeds:
        print(seed)
else:
    print("Nenhuma seed válida encontrada.")

"""
Generate synthetic private data for the local simulation.

Each country gets its own VCFs under nodes/<Country>/data/. In a real
deployment this script does not exist on the central node -- the data is
already sitting inside each country and never moves.

The countries share one pool of variants at a common underlying frequency,
each drifts away from it, and each carries some variants nobody else has --
which is what gives the Balding-Nichols filter something to see through.

usage: make_mock_data.py [n_samples] [n_shared] [n_private]
"""
import gzip, os, random, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COUNTRIES = ["Spain", "Germany", "Czechia"]

HEADER = ('##fileformat=VCFv4.2\n'
          '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
          '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t{sample}\n')


def genotype(freq, rng):
    return f"{'1' if rng.random() < freq else '0'}/{'1' if rng.random() < freq else '0'}"


def main():
    n_samples = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    n_shared  = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    n_private = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    rng = random.Random(20260902)

    shared = [("1", 100000 + 137 * i, "A", "G", rng.uniform(0.05, 0.45))
              for i in range(n_shared)]

    for idx, country in enumerate(COUNTRIES):
        variants = [(c, p, r, a, min(0.95, max(0.02, f + rng.gauss(0, 0.08))))
                    for (c, p, r, a, f) in shared]
        variants += [("2", 200000 + 211 * i + idx, "C", "T", rng.uniform(0.05, 0.40))
                     for i in range(n_private)]
        variants.sort(key=lambda v: (v[0], v[1]))

        data_dir = os.path.join(ROOT, "nodes", country, "genomic_varcalls")
        os.makedirs(data_dir, exist_ok=True)
        for s in range(1, n_samples + 1):
            sample = f"{country}_{s:03d}"
            with gzip.open(os.path.join(data_dir, f"{sample}.vcf.gz"), "wt") as fh:
                fh.write(HEADER.format(sample=sample))
                for chrom, pos, ref, alt, freq in variants:
                    fh.write(f"{chrom}\t{pos}\t.\t{ref}\t{alt}\t.\tPASS\t.\tGT\t"
                             f"{genotype(freq, rng)}\n")
        print(f"{country}: {n_samples} samples x {len(variants)} variants -> {data_dir}")


if __name__ == "__main__":
    main()

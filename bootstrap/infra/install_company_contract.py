"""Replace conflicting append-only SOUL blocks; preserve backup via maintenance."""
from pathlib import Path
import yaml

MISSIONS = {
    'produto': 'PM e UX Researcher. Entrevistar CEO, brief, histórias e critérios. Não implementar mockups/código. Coordenação técnica pertence ao Tech Lead.',
    'designer': 'UX/UI. Fluxos e estados visualmente verificáveis, acessibilidade e especificações para frontend. Dúvidas de produto vão a produto.',
    'cto': 'CTO. ADRs com alternativas e evidências locais. Autoridade final técnica; revisar Tech Lead e resolver incidentes, sem transferir arquitetura ao CEO.',
    'techlead': 'Tech Lead/Engineering Manager. Cobertura do brief, plano, DAG, capacidade, handoffs, revisão e integração até homologação. Não absorver tarefas de todos.',
    'backend_data': 'Backend e dados. Regras, APIs/eventos, integridade, idempotência, migrações, concorrência, observabilidade sem dados sensíveis.',
    'frontend': 'Web. Interface responsiva, 3D no jogo, performance medida, acessibilidade e estados de erro/reconexão; contratos com backend e design.',
    'mobile': 'Android/iOS quando o brief incluir mobile. v0.1 é WEB: não criar tarefas ou artefatos mobile sem mudança explícita de escopo.',
    'devops': 'DevOps/SRE local. Compose reproduzível ARM64, CI local, limites, saúde, logs, backup/rollback e SHA implantado; QA valida após deploy.',
    'quality_security': 'QA/SecOps. Testes/regressão, privacidade, segurança e validação independente pós-deploy. Revisar DevOps; seu código é revisado pelo Tech Lead.',
}

if __name__ == '__main__':
    raise SystemExit('Retired installer: use the reviewed, manifest-verified restart source; legacy SOUL writes are disabled.')
    if not Path('/opt/data/kanban/boards/truco-online/MAINTENANCE').exists():
        raise SystemExit('contract installation requires active maintenance fence')
    contract = Path(__file__).with_name('company-contract.md').read_text()
    for profile, mission in MISSIONS.items():
        root = Path('/opt/data/profiles') / profile
        (root / 'SOUL.md').write_text(f'# Perfil {profile}\n\n{mission}\n\n' + contract)
        for skill in root.glob('skills/**/company-delivery-contract/SKILL.md'):
            skill.write_text('---\nname: company-delivery-contract\ndescription: Contrato de execução e entrega do time Truco Online.\n---\n\n' + contract)
        config_path = root / 'config.yaml'
        config = yaml.safe_load(config_path.read_text())
        # Maintain pause; resume is a separate operator action after tests.
        config['kanban']['dispatch_in_gateway'] = False
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    for skill in Path('/opt/data/skills').glob('**/company-delivery-contract/SKILL.md'):
        skill.write_text('---\nname: company-delivery-contract\ndescription: Contrato de execução e entrega do time Truco Online.\n---\n\n' + contract)

// One MF tool binding plus five equipment anchors.

MERGE (tool:CKG_ToolFunction {tool_id: 'mf_t01_fourier_1d'})
SET tool.name = 'Fourier 1D Heat Conduction',
    tool.description = 'Analytical semi-infinite 1D heat conduction solver for estimating temperature at depth after a surface temperature step.',
    tool.input_params = [
      '{"name":"T_initial","unit":"C","required":true}',
      '{"name":"T_surface","unit":"C","required":true}',
      '{"name":"alpha","unit":"m^2/s","required":true}',
      '{"name":"x","unit":"m","required":true}',
      '{"name":"t","unit":"s","required":true}'
    ],
    tool.output_type = 'temperature_profile',
    tool.version = '1.0',
    tool.langgraph_node = 'mf_t01_node';

MERGE (mf:CKG_MF {mf_id: 'mf_t01'})
SET mf.canonical_name = 'Fourier_1D',
    mf.display_name = '1D unsteady heat conduction',
    mf.equation_latex = 'T(x,t)=T_i+(T_s-T_i)\\operatorname{erfc}\\left(\\frac{x}{2\\sqrt{\\alpha t}}\\right)',
    mf.sympy_expression = 'T_initial + (T_surface - T_initial) * erfc(x / (2 * sqrt(alpha * t)))',
    mf.output_symbol = 'T',
    mf.applicable_range = '{"temperature_c_min":-40.0,"temperature_c_max":300.0,"geometry":"semi_infinite_slab"}',
    mf.assumptions = 'Semi-infinite slab, constant thermal diffusivity, fixed surface temperature step, one-dimensional heat flow.',
    mf.required_variables = ['T_initial', 'T_surface', 'alpha', 'x', 't'],
    mf.default_units = '{"T_initial":"C","T_surface":"C","alpha":"m^2/s","x":"m","t":"s"}';

MATCH (mf:CKG_MF {mf_id: 'mf_t01'})
MATCH (tool:CKG_ToolFunction {tool_id: 'mf_t01_fourier_1d'})
MERGE (mf)-[r:IMPLEMENTED_BY]->(tool)
SET r.version = '1.0',
    r.validation_status = 'validated';

MATCH (p:CKG_PHN {phn_id: 'phn_thermal_protein_denaturation'})
MATCH (mf:CKG_MF {mf_id: 'mf_t01'})
MERGE (p)-[r:GOVERNED_BY_MF]->(mf)
SET r.applicability = 'Heat conduction controls the temperature history that triggers denaturation at depth.',
    r.assumptions = 'Local temperature can be approximated by 1D conduction during early heating.',
    r.variable_mapping = 'T_initial->T_init; T_surface->T_boundary; x->x_position; t->time';

MATCH (p:CKG_PHN {phn_id: 'phn_maillard_browning'})
MATCH (mf:CKG_MF {mf_id: 'mf_t01'})
MERGE (p)-[r:GOVERNED_BY_MF]->(mf)
SET r.applicability = 'Surface heat transfer controls whether the surface reaches Maillard-active temperatures.',
    r.assumptions = 'A pan-seared food surface is approximated as a fixed high-temperature boundary.',
    r.variable_mapping = 'T_initial->T_init; T_surface->T_boundary; x->x_position; t->time';

UNWIND [
  {
    equipment_id: 'eq_wok',
    name_zh: '铁锅',
    name_en: 'wok',
    category: 'pan',
    heating_mode: 'conduction',
    default_temp_min: 140.0,
    default_temp_max: 260.0,
    l1_ref_id: 'l1_equipment_wok'
  },
  {
    equipment_id: 'eq_clay_pot',
    name_zh: '砂锅',
    name_en: 'clay pot',
    category: 'pot',
    heating_mode: 'conduction',
    default_temp_min: 85.0,
    default_temp_max: 130.0,
    l1_ref_id: 'l1_equipment_clay_pot'
  },
  {
    equipment_id: 'eq_oven',
    name_zh: '烤箱',
    name_en: 'oven',
    category: 'oven',
    heating_mode: 'convection_radiation',
    default_temp_min: 80.0,
    default_temp_max: 260.0,
    l1_ref_id: 'l1_equipment_oven'
  },
  {
    equipment_id: 'eq_pressure_cooker',
    name_zh: '高压锅',
    name_en: 'pressure cooker',
    category: 'pot',
    heating_mode: 'pressurized_steam',
    default_temp_min: 105.0,
    default_temp_max: 121.0,
    l1_ref_id: 'l1_equipment_pressure_cooker'
  },
  {
    equipment_id: 'eq_steamer',
    name_zh: '蒸锅',
    name_en: 'steamer',
    category: 'steamer',
    heating_mode: 'steam_convection',
    default_temp_min: 95.0,
    default_temp_max: 100.0,
    l1_ref_id: 'l1_equipment_steamer'
  }
] AS row
MERGE (e:CKG_Equipment {equipment_id: row.equipment_id})
SET e += row;

MATCH (e:CKG_Equipment {equipment_id: 'eq_wok'})
MATCH (p:CKG_PHN {phn_id: 'phn_maillard_browning'})
MERGE (e)-[r:AFFECTS_PHENOMENON]->(p)
SET r.effect = 'high conductive heat promotes surface browning',
    r.score = 0.9;

MATCH (e:CKG_Equipment {equipment_id: 'eq_pressure_cooker'})
MATCH (p:CKG_PHN {phn_id: 'phn_thermal_protein_denaturation'})
MERGE (e)-[r:AFFECTS_PHENOMENON]->(p)
SET r.effect = 'elevated wet heat accelerates protein denaturation',
    r.score = 0.8;

MATCH (e:CKG_Equipment {equipment_id: 'eq_oven'})
MATCH (p:CKG_PHN {phn_id: 'phn_caramelization'})
MERGE (e)-[r:AFFECTS_PHENOMENON]->(p)
SET r.effect = 'dry radiant and convective heat enables sugar caramelization',
    r.score = 0.8;

MATCH (e:CKG_Equipment {equipment_id: 'eq_steamer'})
MATCH (p:CKG_PHN {phn_id: 'phn_starch_gelatinization'})
MERGE (e)-[r:AFFECTS_PHENOMENON]->(p)
SET r.effect = 'saturated steam supplies water and heat for starch gelatinization',
    r.score = 0.75;

MATCH (e:CKG_Equipment {equipment_id: 'eq_clay_pot'})
MATCH (p:CKG_PHN {phn_id: 'phn_salt_diffusion'})
MERGE (e)-[r:AFFECTS_PHENOMENON]->(p)
SET r.effect = 'long moist holding supports salt diffusion into ingredients',
    r.score = 0.7;

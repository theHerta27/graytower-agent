using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;

// Typed replay state, deliberately independent of the input JObject and of combat rules.
[JsonObject(MemberSerialization.Fields)]
public sealed class BuffSnapshotV2
{
    [JsonProperty(Required=Required.Always)] public string buff_id, source_id, attack_snapshot;
    [JsonProperty(Required=Required.Always)] public int remaining, stacks;
    [JsonProperty(Required=Required.AllowNull)] public int? fresh_turn;
}
[JsonObject(MemberSerialization.Fields)]
public sealed class ShieldSnapshotV2
{
    [JsonProperty(Required=Required.Always)] public string source_id, skill_id;
    [JsonProperty(Required=Required.Always)] public int value, remaining, created_seq;
    [JsonProperty(Required=Required.AllowNull)] public int? fresh_turn;
}
[JsonObject(MemberSerialization.Fields)]
public sealed class UnitSnapshotV2
{
    [JsonProperty(Required=Required.Always)] public int hp, max_hp, energy, energy_max, toughness, toughness_max, slot, skill_index;
    [JsonProperty(Required=Required.Always)] public bool broken, dead, speed_passive;
    [JsonProperty(Required=Required.Always)] public string side, remaining_distance, spd, atk, defense, crit_rate, crit_damage_bonus, damage_bonus;
    [JsonProperty(Required=Required.AllowNull)] public string template_id, charging;
    [JsonProperty(Required=Required.Always)] public List<string> weaknesses;
    [JsonProperty(Required=Required.Always)] public Dictionary<string,BuffSnapshotV2> buffs;
    [JsonProperty(Required=Required.Always)] public List<ShieldSnapshotV2> shields;
}
[JsonObject(MemberSerialization.Fields)]
public sealed class BattleSnapshotV2
{
    [JsonProperty(Required=Required.Always)] public Dictionary<string,UnitSnapshotV2> units;
    [JsonProperty(Required=Required.Always)] public int skill_points, phase_index, phase_action_count, enrage_stacks, normal_turn_count, action_count, shield_seq, summon_seq, rng_count;
    [JsonProperty(Required=Required.Always)] public string elapsed_av;
    [JsonProperty(Required=Required.AllowNull)] public string current_actor, action_id;
    [JsonProperty(Required=Required.Always)] public bool ultimate_used, normal_used;
}

public sealed class CombatStateV2 : MonoBehaviour
{
    public BattleSnapshotV2 State;
    static JsonSerializer Serializer() { return JsonSerializer.Create(new JsonSerializerSettings{MissingMemberHandling=MissingMemberHandling.Error}); }
    public static BattleSnapshotV2 Parse(JObject value)
    {
        if(value==null) throw new InvalidDataException("Missing BattleState 2.0");
        var result=value.ToObject<BattleSnapshotV2>(Serializer());
        if(result.units.Count==0 || result.skill_points<0 || result.skill_points>5 || result.phase_index<0)
            throw new InvalidDataException("Invalid global state");
        foreach(var u in result.units.Values)
            if(u.hp<0 || u.hp>u.max_hp || u.energy<0 || u.energy>u.energy_max || u.toughness<0 || u.toughness>u.toughness_max || (u.side!="player" && u.side!="enemy"))
                throw new InvalidDataException("Invalid unit state");
        return result;
    }
    public void Load(JObject value)
    {
        State=Parse(value);
        // Units are owned by CombatUnitView, never retained as a second readback source.
        State.units.Clear();
    }
    public JObject Export(IEnumerable<CombatUnitView> views)
    {
        var result=JObject.FromObject(State);
        var units=new JObject(); foreach(var unit in views) units[unit.Id]=unit.Export();
        result["units"]=units; return result;
    }
    public static void ValidateTrace(JObject trace)
    {
        if((string)trace["contract_version"]!="2.0" || !(trace["phase_ids"] is JArray phases) || phases.Count==0)
            throw new InvalidDataException("Missing Contract 2.0 metadata");
        var initial=Parse(trace["initial_state"] as JObject);
        var events=(JArray)trace["events"];
        if((string)events[0]["kind"]!="battle_started" || (string)events.Last["kind"]!="battle_finished")
            throw new InvalidDataException("Incomplete Trace 2.0");
        var seen=new HashSet<string>();
        for(int i=0;i<events.Count;i++)
        {
            var e=events[i]; var state=Parse(e["state_after"] as JObject);
            string id=(string)e["event_id"],cause=(string)e["cause_event_id"];
            if(id!="event_"+(i+1).ToString("D6") || (cause!=null && !seen.Contains(cause)) || state.phase_index>=phases.Count)
                throw new InvalidDataException("Invalid event sequence, cause or phase");
            foreach(var field in new[]{"actor_id","target_id"})
                if(e[field]?.Type!=JTokenType.Null && (e[field]==null || !state.units.ContainsKey((string)e[field])))
                    throw new InvalidDataException("Unknown event unit");
            seen.Add(id);
        }
        if(!JToken.DeepEquals(events[0]["state_after"],trace["initial_state"]) ||
           !JToken.DeepEquals(events.Last["state_after"],trace["result"]["final_state"]) ||
           !JToken.DeepEquals(events.Last["payload"]["outcome"],trace["result"]["outcome"]) ||
           !JToken.DeepEquals(events.Last["payload"]["reason"],trace["result"]["reason"]))
            throw new InvalidDataException("Trace endpoints do not match state/result");
    }
}

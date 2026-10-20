import com.healthmarketscience.jackcess.*;
import com.healthmarketscience.jackcess.util.*;
import java.io.*;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;

/**
 * Folio's bridge to Microsoft Access files (.accdb / .mdb), built on Jackcess.
 *
 *   read  <file>            prints the whole database as JSON on stdout
 *   write <file> <spec.json> creates a new Access file from a JSON description
 *   serve <file>            keeps the file open and answers JSON requests, one per line on
 *                           stdin, one JSON answer per line on stdout (native editing)
 *
 * Types are the Folio ones: autonumber, integer, number, boolean, date, datetime,
 * text, longtext. Errors go to stderr with exit code 2.
 */
public final class FolioAccess {
    private static final DateTimeFormatter DAY = DateTimeFormatter.ofPattern("yyyy-MM-dd");
    private static final DateTimeFormatter STAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    public static void main(String[] args) {
        try {
            if (args.length == 2 && args[0].equals("read")) {
                PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), false, "UTF-8");
                read(new File(args[1]), out);
                out.flush();
            } else if (args.length == 2 && args[0].equals("serve")) {
                serve(new File(args[1]));
            } else if (args.length == 3 && args[0].equals("write")) {
                String text = new String(Files.readAllBytes(Paths.get(args[2])), StandardCharsets.UTF_8);
                write(new File(args[1]), (Map<String, Object>) new Json(text).parse());
            } else {
                System.err.println("usage: read <file> | write <file> <spec.json>");
                System.exit(2);
            }
        } catch (Throwable e) {
            System.err.println(e.getClass().getSimpleName() + ": " + e.getMessage());
            System.exit(2);
        }
    }

    // ---- reading ---------------------------------------------------------------------

    private static void read(File file, PrintStream out) throws IOException {
        try (Database db = new DatabaseBuilder(file).setReadOnly(true).open()) {
            db.setDateTimeType(DateTimeType.LOCAL_DATE_TIME);
            out.print(dump(db));
        }
    }

    private static String dump(Database db) throws IOException {
        {
            StringBuilder sb = new StringBuilder("{\"tables\":[");
            boolean firstTable = true;
            List<String> names = new ArrayList<>(db.getTableNames());
            Collections.sort(names, String.CASE_INSENSITIVE_ORDER);
            for (String name : names) {
                Table table = db.getTable(name);
                if (!firstTable) sb.append(',');
                firstTable = false;
                tableJson(table, sb);
            }
            sb.append("],\"relationships\":[");
            boolean first = true;
            for (Relationship r : db.getRelationships()) {
                if (r.getFromColumns().size() != 1) continue; // composite links aren't carried over
                if (!first) sb.append(',');
                first = false;
                sb.append("{\"parent\":").append(str(r.getFromTable().getName()))
                  .append(",\"parentField\":").append(str(r.getFromColumns().get(0).getName()))
                  .append(",\"child\":").append(str(r.getToTable().getName()))
                  .append(",\"childField\":").append(str(r.getToColumns().get(0).getName()))
                  .append(",\"cascade\":").append(r.cascadeDeletes())
                  .append(",\"setNull\":").append(r.cascadeNullOnDelete()).append('}');
            }
            sb.append("]}");
            return sb.toString();
        }
    }

    private static String kind(Column c) throws IOException {
        switch (c.getType()) {
            case BOOLEAN: return "boolean";
            case BYTE: case INT: case LONG: return c.isAutoNumber() ? "autonumber" : "integer";
            case MONEY: return "currency";
            case FLOAT: case DOUBLE: case NUMERIC:
                return currencyOf(c) != null ? "currency" : "number";
            case SHORT_DATE_TIME: return "datetime";
            case TEXT: case GUID: return "text";
            case MEMO: return "longtext";
            default: return null; // pictures, attachments, OLE objects…
        }
    }

    /** The currency code of a column shown as money (Format or CurrencyLCID), else null. */
    private static String currencyOf(Column c) {
        String format = "";
        Object lcid = null;
        try {
            Object f = c.getProperties().getValue(PropertyMap.FORMAT_PROP);
            if (f != null) format = f.toString();
            lcid = c.getProperties().getValue("CurrencyLCID");
        } catch (Exception e) { /* properties are optional */ }
        String lower = format.toLowerCase();
        String[][] signs = {{"€", "EUR"}, {"$", "USD"}, {"£", "GBP"}, {"₽", "RUB"}, {"¥", "JPY"}, {"₹", "INR"}, {"zł", "PLN"}, {"Kč", "CZK"}};
        for (String[] s : signs) if (format.contains(s[0])) return s[1];
        boolean money = c.getType() == DataType.MONEY || lower.equals("currency") || lower.equals("euro");
        if (!money) return null;
        if (lower.equals("euro")) return "EUR";
        int l = lcid instanceof Number ? ((Number) lcid).intValue() : 0;
        switch (l) {
            case 1033: case 4105: case 3081: return l == 1033 ? "USD" : (l == 4105 ? "CAD" : "AUD");
            case 2057: return "GBP";
            case 1049: return "RUB";
            case 1041: return "JPY";
            case 1045: return "PLN";
            case 2055: case 4108: return "CHF";
            default: return "EUR";
        }
    }

    private static void tableJson(Table table, StringBuilder sb) throws IOException {
        Set<String> keys = new LinkedHashSet<>();
        Set<String> unique = new HashSet<>();
        for (Index ix : table.getIndexes()) {
            if (ix.getColumns().isEmpty()) continue;
            if (ix.isPrimaryKey()) for (Index.Column ic : ix.getColumns()) keys.add(ic.getName());
            else if (ix.isUnique() && ix.getColumns().size() == 1 && !ix.isForeignKey())
                unique.add(ix.getColumns().get(0).getName());
        }
        List<Column> kept = new ArrayList<>();
        List<String> skipped = new ArrayList<>();
        for (Column c : table.getColumns()) {
            if (kind(c) == null) skipped.add(c.getName()); else kept.add(c);
        }
        // a datetime column whose values are all midnight is a date
        Map<String, Boolean> onlyDays = new HashMap<>();
        for (Column c : kept) onlyDays.put(c.getName(), true);
        List<Row> rows = new ArrayList<>();
        for (Row row : table) {
            rows.add(row);
            for (Column c : kept) {
                Object v = row.get(c.getName());
                if (v instanceof LocalDateTime && !((LocalDateTime) v).toLocalTime().equals(LocalTime.MIDNIGHT))
                    onlyDays.put(c.getName(), false);
            }
        }
        sb.append("{\"name\":").append(str(table.getName())).append(",\"columns\":[");
        for (int i = 0; i < kept.size(); i++) {
            Column c = kept.get(i);
            String k = kind(c);
            if (k.equals("datetime") && onlyDays.get(c.getName())) k = "date";
            boolean required = false;
            try { required = Boolean.TRUE.equals(c.getProperties().getValue(PropertyMap.REQUIRED_PROP)); }
            catch (Exception e) { /* properties are optional */ }
            if (i > 0) sb.append(',');
            sb.append("{\"name\":").append(str(c.getName())).append(",\"type\":").append(str(k))
              .append(",\"key\":").append(keys.contains(c.getName()))
              .append(",\"unique\":").append(unique.contains(c.getName()))
              .append(",\"required\":").append(required)
              .append(",\"currency\":").append(str(k.equals("currency") ? currencyOf(c) == null ? "EUR" : currencyOf(c) : ""))
              .append('}');
        }
        sb.append("],\"skipped\":[");
        for (int i = 0; i < skipped.size(); i++) sb.append(i > 0 ? "," : "").append(str(skipped.get(i)));
        sb.append("],\"rows\":[");
        boolean first = true;
        for (Row row : rows) {
            if (!first) sb.append(',');
            first = false;
            sb.append('[');
            for (int i = 0; i < kept.size(); i++) {
                Column c = kept.get(i);
                if (i > 0) sb.append(',');
                value(row.get(c.getName()), onlyDays.get(c.getName()), sb);
            }
            sb.append(']');
        }
        sb.append("]}");
    }

    private static void value(Object v, boolean day, StringBuilder sb) {
        if (v == null) sb.append("null");
        else if (v instanceof Boolean) sb.append(v);
        else if (v instanceof BigDecimal) sb.append(((BigDecimal) v).toPlainString());
        else if (v instanceof Double || v instanceof Float) {
            double d = ((Number) v).doubleValue();
            sb.append(Double.isFinite(d) ? Double.toString(d) : "null");
        } else if (v instanceof Number) sb.append(v);
        else if (v instanceof LocalDateTime) sb.append(str(day ? ((LocalDateTime) v).format(DAY) : ((LocalDateTime) v).format(STAMP)));
        else sb.append(str(v.toString()));
    }

    private static String str(String s) {
        StringBuilder sb = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char ch = s.charAt(i);
            switch (ch) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (ch < 0x20) sb.append(String.format("\\u%04x", (int) ch)); else sb.append(ch);
            }
        }
        return sb.append('"').toString();
    }

    // ---- writing ---------------------------------------------------------------------

    @SuppressWarnings("unchecked")
    private static void write(File file, Map<String, Object> spec) throws IOException {
        if (file.exists() && file.length() > 0) throw new IOException("the file already exists");
        boolean legacy = file.getName().toLowerCase().endsWith(".mdb");
        Database.FileFormat format = legacy ? Database.FileFormat.V2000 : Database.FileFormat.V2010;
        try (Database db = new DatabaseBuilder(file).setFileFormat(format).create()) {
            db.setDateTimeType(DateTimeType.LOCAL_DATE_TIME);
            db.setAllowAutoNumberInsert(Boolean.TRUE);
            List<Object> tables = (List<Object>) spec.get("tables");
            for (Object t : tables) {
                Map<String, Object> table = (Map<String, Object>) t;
                createTable(db, table);
            }
            for (Object t : tables) fill(db, (Map<String, Object>) t);
            List<Object> rels = (List<Object>) spec.getOrDefault("relationships", new ArrayList<>());
            int n = 1;
            for (Object r : rels) addRelationship(db, (Map<String, Object>) r, n++);
        }
    }

    @SuppressWarnings("unchecked")
    private static void createTable(Database db, Map<String, Object> table) throws IOException {
        TableBuilder tb = new TableBuilder((String) table.get("name"));
        List<String> keys = new ArrayList<>();
        List<String> unique = new ArrayList<>();
        for (Object c : (List<Object>) table.get("columns")) {
            Map<String, Object> col = (Map<String, Object>) c;
            String name = (String) col.get("name");
            ColumnBuilder cb = new ColumnBuilder(name);
            switch ((String) col.get("type")) {
                case "autonumber": cb.setType(DataType.LONG).setAutoNumber(true); break;
                case "integer": cb.setType(DataType.LONG); break;
                case "number": cb.setType(DataType.DOUBLE); break;
                case "currency": cb.setType(DataType.MONEY); break;
                case "boolean": cb.setType(DataType.BOOLEAN); break;
                case "date": case "datetime": cb.setType(DataType.SHORT_DATE_TIME); break;
                case "longtext": cb.setType(DataType.MEMO); break;
                default: cb.setType(DataType.TEXT).setMaxLength();
            }
            tb.addColumn(cb);
            if (Boolean.TRUE.equals(col.get("key"))) keys.add(name);
            else if (Boolean.TRUE.equals(col.get("unique"))) unique.add(name);
        }
        if (!keys.isEmpty())
            tb.addIndex(new IndexBuilder(IndexBuilder.PRIMARY_KEY_NAME).addColumns(keys.toArray(new String[0])).setPrimaryKey());
        for (String u : unique) tb.addIndex(new IndexBuilder("uq_" + u).addColumns(u).setUnique());
        Table created = tb.toTable(db);
        for (Object c : (List<Object>) table.get("columns")) {
            Map<String, Object> col = (Map<String, Object>) c;
            if (Boolean.TRUE.equals(col.get("required")) && !Boolean.TRUE.equals(col.get("key"))) {
                PropertyMap props = created.getColumn((String) col.get("name")).getProperties();
                props.put(PropertyMap.REQUIRED_PROP, true);
                props.save();
            }
            if ("currency".equals(col.get("type"))) {
                PropertyMap props = created.getColumn((String) col.get("name")).getProperties();
                String code = col.get("currency") == null ? "EUR" : (String) col.get("currency");
                String sign = code.equals("EUR") ? "€" : code.equals("USD") ? "$" : code.equals("GBP") ? "£"
                    : code.equals("RUB") ? "₽" : code.equals("JPY") ? "¥" : code;
                props.put(PropertyMap.FORMAT_PROP, "#,##0.00 " + sign + ";-#,##0.00 " + sign);
                props.save();
            }
        }
    }

    @SuppressWarnings("unchecked")
    private static void fill(Database db, Map<String, Object> table) throws IOException {
        Table target = db.getTable((String) table.get("name"));
        List<Object> columns = (List<Object>) table.get("columns");
        String[] types = new String[columns.size()];
        for (int i = 0; i < types.length; i++) types[i] = (String) ((Map<String, Object>) columns.get(i)).get("type");
        List<Object[]> rows = new ArrayList<>();
        for (Object r : (List<Object>) table.get("rows")) {
            List<Object> row = (List<Object>) r;
            Object[] values = new Object[types.length];
            for (int i = 0; i < types.length; i++) values[i] = convert(row.get(i), types[i]);
            rows.add(values);
        }
        if (!rows.isEmpty()) target.addRows(rows);
    }

    private static Object convert(Object v, String type) {
        if (v == null) return null;
        switch (type) {
            case "autonumber": case "integer": return ((Number) v).longValue();
            case "number": return ((Number) v).doubleValue();
            case "currency": return BigDecimal.valueOf(((Number) v).doubleValue()).setScale(4, java.math.RoundingMode.HALF_EVEN);
            case "boolean": return v instanceof Boolean ? v : Boolean.valueOf(((Number) v).intValue() != 0);
            case "date": return LocalDate.parse((String) v, DAY).atStartOfDay();
            case "datetime": return LocalDateTime.parse((String) v, STAMP);
            default: return v.toString();
        }
    }


    // ---- serving (native editing) ------------------------------------------------------

    private static void serve(File file) throws IOException {
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), false, "UTF-8");
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        try (Database db = new DatabaseBuilder(file).open()) {
            db.setDateTimeType(DateTimeType.LOCAL_DATE_TIME);
            db.setAllowAutoNumberInsert(Boolean.TRUE);
            String line;
            while ((line = in.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                String answer;
                boolean stop = false;
                try {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> req = (Map<String, Object>) new Json(line).parse();
                    String op = (String) req.get("op");
                    if (op.equals("close")) { stop = true; answer = "{\"ok\":true}"; }
                    else answer = handle(db, op, req);
                } catch (Throwable e) {
                    answer = "{\"ok\":false,\"error\":" + str(e.getClass().getSimpleName() + ": " + e.getMessage()) + "}";
                }
                out.println(answer);
                out.flush();
                if (stop) break;
            }
        }
    }

    @SuppressWarnings("unchecked")
    private static String handle(Database db, String op, Map<String, Object> req) throws IOException {
        switch (op) {
            case "load": return "{\"ok\":true,\"data\":" + dump(db) + "}";
            case "dump": {
                StringBuilder sb = new StringBuilder("{\"ok\":true,\"table\":");
                tableJson(db.getTable((String) req.get("table")), sb);
                return sb.append('}').toString();
            }
            case "insert": {
                Table t = db.getTable((String) req.get("table"));
                Map<String, Object> row = convertRow(t, (Map<String, Object>) req.get("values"));
                Map<String, Object> done = t.addRowFromMap(row);
                StringBuilder sb = new StringBuilder("{\"ok\":true,\"generated\":{");
                boolean first = true;
                for (Column c : t.getColumns()) {
                    if (!c.isAutoNumber()) continue;
                    if (!first) sb.append(',');
                    first = false;
                    sb.append(str(c.getName())).append(':');
                    value(done.get(c.getName()), false, sb);
                }
                return sb.append("}}").toString();
            }
            case "bulkInsert": {
                Table t = db.getTable((String) req.get("table"));
                List<Object> names = (List<Object>) req.get("columns");
                List<Object[]> rows = new ArrayList<>();
                for (Object r : (List<Object>) req.get("rows")) {
                    List<Object> values = (List<Object>) r;
                    Object[] row = new Object[t.getColumnCount()];
                    for (int i = 0; i < names.size(); i++) {
                        Column c = t.getColumn((String) names.get(i));
                        row[c.getColumnIndex()] = fromJson(c, values.get(i));
                    }
                    rows.add(row);
                }
                if (!rows.isEmpty()) t.addRows(rows);
                return "{\"ok\":true}";
            }
            case "update": case "delete": {
                Table t = db.getTable((String) req.get("table"));
                Map<String, Object> match = (Map<String, Object>) req.get("match");
                Cursor c = locate(t, match);
                if (c == null) throw new IOException("the row was not found");
                if (op.equals("delete")) c.deleteCurrentRow();
                else c.updateCurrentRowFromMap(convertRow(t, (Map<String, Object>) req.get("values")));
                return "{\"ok\":true}";
            }
            case "createTable": {
                createTable(db, (Map<String, Object>) req.get("spec"));
                return "{\"ok\":true}";
            }
            case "addColumn": {
                Table t = db.getTable((String) req.get("table"));
                Map<String, Object> col = (Map<String, Object>) req.get("column");
                ColumnBuilder cb = columnBuilder(col);
                cb.addToTable(t);
                if (Boolean.TRUE.equals(col.get("required")) || "currency".equals(col.get("type"))) {
                    setProperties(t.getColumn((String) col.get("name")), col);
                }
                return "{\"ok\":true}";
            }
            case "addRelationship": {
                addRelationship(db, (Map<String, Object>) req.get("relationship"), (int) (System.nanoTime() % 100000));
                return "{\"ok\":true}";
            }
            default: throw new IOException("unknown request " + op);
        }
    }

    /** Finds the row a request means: by primary key when the table has one, else by all values. */
    private static Cursor locate(Table t, Map<String, Object> match) throws IOException {
        Index pk = null;
        for (Index ix : t.getIndexes()) if (ix.isPrimaryKey()) pk = ix;
        if (pk != null) {
            boolean all = true;
            Object[] entry = new Object[pk.getColumns().size()];
            for (int i = 0; i < entry.length; i++) {
                String name = pk.getColumns().get(i).getName();
                if (!match.containsKey(name)) { all = false; break; }
                entry[i] = fromJson(t.getColumn(name), match.get(name));
            }
            if (all) {
                IndexCursor c = CursorBuilder.createCursor(pk);
                return c.findRowByEntry(entry) == null ? null : c;
            }
        }
        Cursor c = t.getDefaultCursor();
        c.beforeFirst();
        while (c.moveToNextRow()) {
            Row row = c.getCurrentRow();
            boolean same = true;
            for (Map.Entry<String, Object> e : match.entrySet()) {
                if (!sameValue(row.get(e.getKey()), fromJson(t.getColumn(e.getKey()), e.getValue()))) { same = false; break; }
            }
            if (same) return c;
        }
        return null;
    }

    private static boolean sameValue(Object a, Object b) {
        if (a == null || b == null) return a == b;
        if (a instanceof BigDecimal || b instanceof BigDecimal || a instanceof Double || b instanceof Double
            || a instanceof Float || b instanceof Float) {
            try { return Math.abs(new BigDecimal(a.toString()).subtract(new BigDecimal(b.toString())).doubleValue()) < 1e-9; }
            catch (NumberFormatException e) { return a.equals(b); }
        }
        if (a instanceof Number && b instanceof Number) return ((Number) a).longValue() == ((Number) b).longValue();
        return a.equals(b);
    }

    private static Map<String, Object> convertRow(Table t, Map<String, Object> values) throws IOException {
        Map<String, Object> row = new LinkedHashMap<>();
        for (Map.Entry<String, Object> e : values.entrySet())
            row.put(e.getKey(), fromJson(t.getColumn(e.getKey()), e.getValue()));
        return row;
    }

    /** A JSON value as the Java object Jackcess wants for this column's real Access type. */
    private static Object fromJson(Column c, Object v) throws IOException {
        if (v == null) return null;
        switch (c.getType()) {
            case BOOLEAN: return v instanceof Boolean ? v : Boolean.valueOf(((Number) v).intValue() != 0);
            case BYTE: return ((Number) v).byteValue();
            case INT: return ((Number) v).shortValue();
            case LONG: return ((Number) v).intValue();
            case MONEY: case NUMERIC:
                return new BigDecimal(v.toString()).setScale(c.getType() == DataType.MONEY ? 4 : c.getScale(), java.math.RoundingMode.HALF_EVEN);
            case FLOAT: return ((Number) v).floatValue();
            case DOUBLE: return ((Number) v).doubleValue();
            case SHORT_DATE_TIME: {
                String s = v.toString();
                return s.length() <= 10 ? LocalDate.parse(s, DAY).atStartOfDay() : LocalDateTime.parse(s, STAMP);
            }
            default: return v.toString();
        }
    }

    private static ColumnBuilder columnBuilder(Map<String, Object> col) {
        ColumnBuilder cb = new ColumnBuilder((String) col.get("name"));
        switch ((String) col.get("type")) {
            case "autonumber": cb.setType(DataType.LONG).setAutoNumber(true); break;
            case "integer": cb.setType(DataType.LONG); break;
            case "number": cb.setType(DataType.DOUBLE); break;
            case "currency": cb.setType(DataType.MONEY); break;
            case "boolean": cb.setType(DataType.BOOLEAN); break;
            case "date": case "datetime": cb.setType(DataType.SHORT_DATE_TIME); break;
            case "longtext": cb.setType(DataType.MEMO); break;
            default: cb.setType(DataType.TEXT).setMaxLength();
        }
        return cb;
    }

    private static void setProperties(Column column, Map<String, Object> col) throws IOException {
        PropertyMap props = column.getProperties();
        if (Boolean.TRUE.equals(col.get("required")) && !Boolean.TRUE.equals(col.get("key")))
            props.put(PropertyMap.REQUIRED_PROP, true);
        if ("currency".equals(col.get("type"))) {
            String code = col.get("currency") == null ? "EUR" : (String) col.get("currency");
            String sign = code.equals("EUR") ? "€" : code.equals("USD") ? "$" : code.equals("GBP") ? "£"
                : code.equals("RUB") ? "₽" : code.equals("JPY") ? "¥" : code;
            props.put(PropertyMap.FORMAT_PROP, "#,##0.00 " + sign + ";-#,##0.00 " + sign);
        }
        props.save();
    }

    private static void addRelationship(Database db, Map<String, Object> rel, int n) throws IOException {
        RelationshipBuilder b = new RelationshipBuilder((String) rel.get("parent"), (String) rel.get("child"))
            .addColumns((String) rel.get("parentField"), (String) rel.get("childField"))
            .setReferentialIntegrity();
        if (Boolean.TRUE.equals(rel.get("cascade"))) b.setCascadeDeletes();
        if (Boolean.TRUE.equals(rel.get("setNull"))) b.setCascadeNullOnDelete();
        b.setName("rel" + n + "_" + rel.get("child") + "_" + rel.get("parent"));
        b.toRelationship(db);
    }

    // ---- a very small JSON reader ----------------------------------------------------------

    private static final class Json {
        private final String s;
        private int i;
        Json(String s) { this.s = s; }

        Object parse() { Object v = value(); ws(); return v; }

        private void ws() { while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++; }

        private Object value() {
            ws();
            char c = s.charAt(i);
            if (c == '{') return object();
            if (c == '[') return array();
            if (c == '"') return string();
            if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
            if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
            if (s.startsWith("null", i)) { i += 4; return null; }
            int start = i;
            while (i < s.length() && "+-0123456789.eE".indexOf(s.charAt(i)) >= 0) i++;
            String n = s.substring(start, i);
            if (n.isEmpty()) throw new IllegalArgumentException("bad JSON at " + i);
            return (n.indexOf('.') >= 0 || n.indexOf('e') >= 0 || n.indexOf('E') >= 0)
                ? (Object) Double.valueOf(n) : (Object) Long.valueOf(n);
        }

        private Map<String, Object> object() {
            Map<String, Object> m = new LinkedHashMap<>();
            i++; ws();
            if (s.charAt(i) == '}') { i++; return m; }
            while (true) {
                ws(); String k = string(); ws(); i++; // the colon
                m.put(k, value()); ws();
                if (s.charAt(i++) == '}') return m;
            }
        }

        private List<Object> array() {
            List<Object> l = new ArrayList<>();
            i++; ws();
            if (s.charAt(i) == ']') { i++; return l; }
            while (true) {
                l.add(value()); ws();
                if (s.charAt(i++) == ']') return l;
            }
        }

        private String string() {
            StringBuilder sb = new StringBuilder();
            i++;
            while (true) {
                char c = s.charAt(i++);
                if (c == '"') return sb.toString();
                if (c != '\\') { sb.append(c); continue; }
                char e = s.charAt(i++);
                switch (e) {
                    case 'n': sb.append('\n'); break;
                    case 'r': sb.append('\r'); break;
                    case 't': sb.append('\t'); break;
                    case 'b': sb.append('\b'); break;
                    case 'f': sb.append('\f'); break;
                    case 'u': sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; break;
                    default: sb.append(e);
                }
            }
        }
    }
}
